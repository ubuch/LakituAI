"""Command-line entry point for processing Mario Kart World scoreboard screenshots.

This module provides the main CLI interface for processing race scoreboards and
calculating player/team points. Results are persisted to SQLite for cumulative
war standings. Supports multiple wars.
"""

import argparse
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from lakituai import config, logic, persistence, war_manager

# A scoreboard identical to the last saved race arriving within this window
# (seconds) is considered a stream rewind, not a new race.
DUPLICATE_WINDOW_SECONDS = 90


def parse_arguments() -> argparse.Namespace:
    """Parse and return command-line arguments.

    Returns:
        Parsed arguments with 'image_path' and war management options.

    Raises:
        SystemExit: If required arguments are missing or invalid.
    """
    parser = argparse.ArgumentParser(
        description="Process a Mario Kart World scoreboard screenshot and calculate points.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m lakituai path/to/screenshot.jpg\n"
            "  python -m lakituai --war 'War 1' path/to/screenshot.jpg\n"
            "  python -m lakituai --list-wars\n"
            "  python -m lakituai --delete-war 2\n"
            "  python -m lakituai --delete-wars 1 2 3\n"
            "  python -m lakituai --delete-race 'War 1' 5\n"
            "  python -m lakituai --list-players\n"
            "  python -m lakituai --add-player 'RK AxeeL'\n"
            "  python -m lakituai --list-team-tags\n"
            "  python -m lakituai --add-team-tag RK\n"
            "  python -m lakituai --chat\n"
            "  python -m lakituai --daemon\n"
            "  python -m lakituai --daemon-stop\n"
            "  python -m lakituai --feed path/to/img1.png path/to/img2.png"
        ),
    )

    # War management (mutually exclusive with image_path)
    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "image_path",
        nargs="?",
        type=str,
        default=None,
        help="Path to the scoreboard screenshot image (JPEG, PNG, etc.)",
    )

    group.add_argument(
        "--list-wars",
        action="store_true",
        help="List all wars with details (races, teams, date)",
    )

    group.add_argument(
        "--delete-war",
        type=int,
        metavar="ID",
        help="Delete a war by ID (use --list-wars to see IDs)",
    )

    group.add_argument(
        "--delete-wars",
        nargs="+",
        metavar="ID",
        help="Delete multiple wars by ID (e.g., --delete-wars 1 2 3)",
    )

    group.add_argument(
        "--delete-race",
        nargs=2,
        metavar=("WAR", "RACE_NUMBER"),
        help="Delete a race by war name and race number (e.g., --delete-race 'War 1' 5)",
    )

    group.add_argument(
        "--reset-db",
        action="store_true",
        help="Reset the database: drop all tables and recreate schema (preserves file)",
    )

    group.add_argument(
        "--chat",
        action="store_true",
        help="Start interactive AI chat session (requires Ollama)",
    )

    group.add_argument(
        "--gui",
        action="store_true",
        help="Launch desktop GUI",
    )

    group.add_argument(
        "--list-players",
        action="store_true",
        help="List all registered players",
    )

    group.add_argument(
        "--add-player",
        type=str,
        metavar="NAME",
        help="Add a player (e.g., --add-player 'RK AxeeL')",
    )

    group.add_argument(
        "--list-team-tags",
        action="store_true",
        help="List all registered team tags",
    )

    group.add_argument(
        "--add-team-tag",
        type=str,
        metavar="TAG",
        help="Add a team tag (e.g., --add-team-tag RK)",
    )

    group.add_argument(
        "--daemon",
        action="store_true",
        help="Run the background scoreboard watcher daemon (auto OCR)",
    )

    group.add_argument(
        "--daemon-stop",
        action="store_true",
        help="Stop a running background scoreboard watcher daemon",
    )

    group.add_argument(
        "--feed",
        nargs="+",
        metavar="IMG",
        help="Run the scoreboard detector over static images and report "
        "gate verdicts (no OCR, no DB)",
    )

    # Save even if the screenshot looks like a repeated (rewound) scoreboard
    parser.add_argument(
        "--force",
        action="store_true",
        help="Save the race even if it looks like the last race replayed",
    )

    # War selection (only with image_path)
    parser.add_argument(
        "--war",
        type=str,
        default=None,
        help="War name (defaults to current war)",
        dest="war",
    )

    args = parser.parse_args()
    if (
        args.image_path is None
        and not args.list_wars
        and args.delete_war is None
        and not args.delete_wars
        and args.delete_race is None
        and not args.reset_db
        and not args.chat
        and not args.gui
        and not args.list_players
        and args.add_player is None
        and not args.list_team_tags
        and args.add_team_tag is None
        and not args.daemon
        and not args.daemon_stop
        and args.feed is None
    ):
        parser.error(
            "Image path required "
            "(or use --list-wars, --delete-war, --delete-wars, --delete-race, "
            "--reset-db, --chat, --gui, --list-players, --add-player, "
            "--list-team-tags, --add-team-tag, --daemon, --daemon-stop, --feed)"
        )
    return args


def validate_image_path(image_path: str) -> Path:
    """Validate that the image path exists and is a file.

    Args:
        image_path: String path to the image file.

    Returns:
        Validated Path object.

    Raises:
        FileNotFoundError: If file doesn't exist or is a directory.
        ValueError: If file extension is not a common image format.
    """
    path = Path(image_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {image_path}")

    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
    if path.suffix.lower() not in valid_extensions:
        raise ValueError(
            f"Unsupported image format: {path.suffix}. "
            f"Supported formats: {', '.join(valid_extensions)}"
        )

    return path


def process_scoreboard(
    image_path: Path,
    war_name: str = "Default",
    force: bool = False,
    confirm_rewind: Optional[Callable[[str], bool]] = None,
) -> Optional[int]:
    """Process a scoreboard image and persist results to SQLite + JSON.

    Extracts scoreboard rows from image, runs OCR, matches players, and
    calculates race points. Results are:
    - Saved to JSON (resources/results/race_n_TAG1-TAG2_YYYY_MM_DD.json)
    - Inserted into SQLite war database (resources/war.db)
    - Printed to stdout for user feedback

    If the scoreboard matches the last saved race and arrives within
    DUPLICATE_WINDOW_SECONDS, it is treated as a stream rewind. In that case
    the race is NOT saved by default; the caller can ask the user through
    confirm_rewind (called with an explanation, returns True to save anyway).
    force=True saves without asking.

    Args:
        image_path: Path to the scoreboard image.
        war_name: Name of the war (defaults to "Default").
        force: Save the race even if it looks like the last one replayed.
        confirm_rewind: Optional callable invoked when a rewind is detected
            and force=False. It receives the detection message and returns
            True if the user wants to save the race anyway. If None, the
            race is skipped.

    Returns:
        The saved race number, or None if the race was skipped.

    Raises:
        FileNotFoundError: If image cannot be read.
        ValueError: If OCR or processing fails.
    """
    print(f"Processing image: {image_path}")
    print("-" * 80)

    try:
        # Initialize database and get/create war
        persistence.init_db()
        war_id = persistence.get_or_create_war(war_name)

        # Process image through OCR pipeline
        from lakituai import ocr

        row_paths = logic.prepare_scoreboard_rows(image_path)
        print(f"Extracted {len(row_paths)} scoreboard rows")

        processor, model = ocr.init_ocr()
        ocr_results = ocr.run_ocr(processor, model, row_paths)
        scoreboard_rows = logic.build_scoreboard_results(ocr_results)

        print("\nSCOREBOARD RESULTS:")
        print("-" * 80)
        for row in scoreboard_rows:
            row_type = (
                "BOT"
                if row.is_bot
                else "MISSING" if row.is_missing_player else "PLAYER"
            )
            print(
                f"ROW {row.row_number:2d} [{row_type:7s}]: {row.ocr_text:20s} -> "
                f"{row.normalized_text:20s} -> {row.matched_player:15s} || "
                f"POINTS: {row.points:2d} TO: {row.points_recipient:15s} || "
                f"MATCH: {row.match_score:5.1f} ({row.match_source})"
            )

        # Rewind/duplicate detection: same scoreboard as the last race saved
        # within DUPLICATE_WINDOW_SECONDS is almost certainly the stream
        # being replayed. Ask before saving unless --force.
        race_fingerprint = logic.build_race_fingerprint(scoreboard_rows)
        last_race = persistence.get_last_race(war_id)
        if last_race and last_race["fingerprint"] == race_fingerprint:
            elapsed = _seconds_since(last_race["created_at"])
            if elapsed is not None and elapsed <= DUPLICATE_WINDOW_SECONDS:
                message = (
                    "Possible duplicate/rewind detected: same scoreboard as "
                    f"race #{last_race['race_number']} ({elapsed:.0f}s ago)."
                )
                print(f"\n{message}")
                if force:
                    print("Saving anyway because --force was used.")
                elif confirm_rewind is not None and confirm_rewind(message):
                    print("Saving anyway (confirmed).")
                else:
                    print("Skipping. Use --force to save it anyway.")
                    return None

        # Race numbers are per war: each war restarts at race #1.
        race_number = persistence.get_next_race_number(war_id)

        # JSON files live in a per-war subdirectory so two wars can both
        # have a race #1 without filename collisions.
        results_dir = logic.RESOURCES_DIR / "results" / f"war_{war_id}"
        results_dir.mkdir(parents=True, exist_ok=True)

        # Derive team tags from standings
        team_keys = list(logic.build_team_points(scoreboard_rows).keys())
        tag1 = team_keys[0] if len(team_keys) >= 1 else "teamA"
        tag2 = (
            team_keys[1]
            if len(team_keys) >= 2
            else ("teamB" if len(team_keys) == 1 else "teamA")
        )

        # Sanitize tags for filenames
        def _sanitize(s: str) -> str:
            s = str(s).replace(" ", "_")
            return re.sub(r"[^A-Za-z0-9_\-]", "", s)

        tag1_s = _sanitize(tag1) or "teamA"
        tag2_s = _sanitize(tag2) or "teamB"

        # Save race JSON
        date_str = datetime.utcnow().strftime("%Y_%m_%d")
        json_filename = f"race_{race_number}_{tag1_s}-{tag2_s}_{date_str}.json"
        json_path = results_dir / json_filename

        race_team_points = logic.build_team_points(scoreboard_rows)
        race_json = {
            "image_path": str(image_path),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "rows": [],
            "standings": {
                "player_points": logic.build_player_points(scoreboard_rows),
                "team_points": race_team_points,
                "net_points": logic.build_net_points(race_team_points),
            },
        }

        for row in scoreboard_rows:
            race_json["rows"].append(
                {
                    "row_number": row.row_number,
                    "ocr_text": row.ocr_text,
                    "normalized_text": row.normalized_text,
                    "matched_player": row.matched_player,
                    "points_recipient": row.points_recipient,
                    "points": row.points,
                    "match_score": row.match_score,
                    "match_source": row.match_source,
                    "is_bot": row.is_bot,
                    "is_missing_player": row.is_missing_player,
                }
            )

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(race_json, f, ensure_ascii=False, indent=2)

        print(f"\nSaved race JSON to: {json_path}")

        # Save race to SQLite
        persistence.save_race(
            war_id=war_id,
            race_number=race_number,
            image_path=str(image_path),
            json_path=str(json_path),
            scoreboard_rows=scoreboard_rows,
            fingerprint=race_fingerprint,
        )
        print(f"Saved race #{race_number} to database")

        # Update standings in SQLite
        persistence.update_standings(war_id, scoreboard_rows)

        # Retrieve and display cumulative standings from SQLite
        player_standings = persistence.get_player_standings(war_id)
        team_standings = persistence.get_team_standings(war_id)
        races_played = persistence.get_races_played(war_id)

        print("\n" + "=" * 80)
        print("WAR STANDINGS (CUMULATIVE)")
        print("=" * 80)
        print("\nPLAYER POINTS:")
        for player, points in player_standings.items():
            print(f"  {player:20s}: {points:3d}")

        print("\nTEAM POINTS:")
        for team, points in team_standings.items():
            print(f"  {team:20s}: {points:3d}")

        print(f"\nRaces played: {races_played}")

        return race_number

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"ERROR processing image: {e}", file=sys.stderr)
        raise


def _confirm_rewind(message: str) -> bool:
    """Ask the user whether to save a race that looks like a rewind.

    Defaults to no when stdin is not interactive (e.g. scripts), so
    automated runs never get stuck or save unintended duplicates.

    Args:
        message: Detection message shown to the user.

    Returns:
        True if the user confirmed saving the race.
    """
    if not sys.stdin.isatty():
        return False
    try:
        response = (
            input(f"\n{message}\nAdd the race anyway? (yes/no): ")
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        return False
    return response == "yes"


def _seconds_since(created_at: str) -> Optional[float]:
    """Seconds elapsed between a SQLite timestamp and now (UTC).

    Args:
        created_at: Timestamp string from SQLite ("YYYY-MM-DD HH:MM:SS", UTC).

    Returns:
        Seconds as float, or None if the timestamp cannot be parsed.
    """
    try:
        ts = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return (datetime.utcnow() - ts).total_seconds()


def list_wars_cmd() -> None:
    """List all wars with metadata."""
    persistence.init_db()
    wars = persistence.list_wars()

    if not wars:
        print("No wars found.")
        return

    print("\n" + "=" * 100)
    print("WARS")
    print("=" * 100)

    for t in wars:
        teams_str = ", ".join(t["teams"]) if t["teams"] else "—"
        print(f"\nID #{t['war_id']}: {t['name']}")
        print(f"  Created: {t['created_at']}")
        print(f"  Races: {t['races_count']}")
        print(f"  Teams: {teams_str}")

    print("\n" + "=" * 100)


def delete_war_cmd(war_id: int) -> None:
    """Delete a war by ID."""
    delete_wars_cmd([war_id])


def delete_wars_cmd(war_ids: list[int]) -> None:
    """Delete one or more wars by ID."""
    persistence.init_db()
    wars = persistence.list_wars()
    war_map = {w["war_id"]: w for w in wars}

    # Validate all IDs before prompting
    not_found = [wid for wid in war_ids if wid not in war_map]
    if not_found:
        print(f"ERROR: War ID(s) not found: {', '.join(str(i) for i in not_found)}")
        sys.exit(1)

    # Show summary
    total_races = sum(war_map[wid]["races_count"] for wid in war_ids)
    print(f"\nWars to delete ({len(war_ids)}):")
    for wid in war_ids:
        w = war_map[wid]
        print(f"  #{wid}: {w['name']} ({w['races_count']} race(s))")
    print(f"\nTotal: {len(war_ids)} war(s), {total_races} race(s)")

    response = input("\nConfirm deletion? (yes/no): ").strip().lower()
    if response != "yes":
        print("Deletion cancelled.")
        return

    if persistence.delete_wars(war_ids):
        print(f"✓ Deleted {len(war_ids)} war(s).")
    else:
        print("ERROR: Deletion failed.")
        sys.exit(1)


def delete_race_cmd(war_name: str, race_number: int) -> None:
    """Delete a single race by war name and race number.

    Standings are recalculated after the deletion so cumulative points stay
    consistent with the remaining races.
    """
    persistence.init_db()
    war_id = persistence.get_war_by_name(war_name)
    if war_id is None:
        print(f"ERROR: War '{war_name}' not found.")
        sys.exit(1)

    race = persistence.get_race(war_id, race_number)
    if race is None:
        print(f"ERROR: Race #{race_number} not found in war '{war_name}'.")
        sys.exit(1)

    print(f"\nWar: {war_name}")
    print(f"Race #{race_number} created at: {race['created_at']}")

    response = (
        input(f"\nDelete race #{race_number} from '{war_name}'? (yes/no): ")
        .strip()
        .lower()
    )
    if response != "yes":
        print("Deletion cancelled.")
        return

    if persistence.delete_race(war_id, race_number):
        print(
            f"✓ Deleted race #{race_number} from '{war_name}'. "
            "Standings recalculated."
        )
    else:
        print(f"ERROR: Race #{race_number} not found in war '{war_name}'.")
        sys.exit(1)


def chat_cmd() -> None:
    """Start the interactive AI chat session."""
    from lakituai.chat.agents import run_chat

    run_chat()


def gui_cmd() -> None:
    """Launch the desktop GUI."""
    config.seed_config_files()
    from lakituai.gui.app import run_gui

    run_gui()


def daemon_cmd() -> None:
    """Run the background scoreboard watcher daemon."""
    from lakituai import daemon as daemon_module

    daemon_module.run_daemon_main()


def daemon_stop_cmd() -> None:
    """Stop a running background scoreboard watcher daemon."""
    from lakituai import daemon as daemon_module

    sys.exit(daemon_module.stop_daemon())


def feed_cmd(image_paths: list[str]) -> None:
    """Run the scoreboard detector over static images (no OCR, no DB).

    For each image reports the panel-zone size, the largest connected
    saturated fraction vs the configured gate, and the per-band coverage
    minimum (complete-panel check), so the detector can be validated and
    calibrated against real screenshots without touching the screen.
    """
    import cv2

    from lakituai import detect

    daemon_cfg = config.load_config().daemon
    gate = daemon_cfg.gate_fraction
    min_band = daemon_cfg.complete_min_band
    min_edge = daemon_cfg.complete_min_edge

    print("SCOREBOARD DETECTOR FEED")
    print("-" * 80)
    for raw in image_paths:
        path = validate_image_path(raw)
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"ERROR: could not read image: {path}", file=sys.stderr)
            sys.exit(1)

        zone = detect.crop_zone(frame)
        fraction = detect.largest_cc_fraction(zone)
        bands_min = float(detect.band_coverage(zone).min())
        edges_min = float(detect.edge_band_coverage(zone).min())
        verdict = (
            "SCOREBOARD"
            if detect.is_scoreboard(zone, gate, min_band, min_edge)
            else "not scoreboard"
        )
        y1, y2, x1, x2 = detect.zone_rect(frame.shape)
        print(
            f"{path.name:45s} {frame.shape[1]:5d}x{frame.shape[0]:<4d} "
            f"zone=({x1},{y1})-({x2},{y2}) frac={fraction:5.2f} "
            f"min_band={bands_min:5.2f} min_edge={edges_min:5.2f} "
            f"(req {gate:.2f}/{min_band:.2f}/{min_edge:.2f}) -> {verdict}"
        )
    print("-" * 80)


def list_players_cmd() -> None:
    """List all registered players."""
    from lakituai import player_management

    players = player_management.get_players()
    if not players:
        print("No players registered.")
        print("Use --add-player 'NAME' to add players.")
        return

    print("\nREGISTERED PLAYERS:")
    print("-" * 40)
    for player in players:
        print(f"  {player}")
    print(f"\nTotal: {len(players)}")


def add_player_cmd(name: str) -> None:
    """Add a player."""
    from lakituai import player_management

    success, msg = player_management.add_player(name)
    if success:
        print(f"✓ {msg}")
    else:
        print(f"ERROR: {msg}")
        sys.exit(1)


def list_team_tags_cmd() -> None:
    """List all registered team tags."""
    from lakituai import config

    cfg = config.load_config()
    if not cfg.team_tags:
        print("No team tags configured.")
        print("Use --add-team-tag TAG to add tags.")
        return

    print("\nTEAM TAGS:")
    print("-" * 40)
    for tag in cfg.team_tags:
        print(f"  {tag}")
    print(f"\nTotal: {len(cfg.team_tags)}")


def add_team_tag_cmd(tag: str) -> None:
    """Add a team tag."""
    from lakituai import config

    cfg = config.load_config()
    if tag in cfg.team_tags:
        print(f"Team tag '{tag}' already exists.")
        return

    updated_tags = list(cfg.team_tags) + [tag]
    cfg.team_tags = updated_tags
    config.save_config(cfg)
    print(f"✓ Team tag '{tag}' added. Current tags: {', '.join(cfg.team_tags)}")


def reset_db_cmd() -> None:
    """Reset the database by dropping all tables and recreating schema."""
    persistence.init_db()
    wars = persistence.list_wars()
    total_races = sum(w["races_count"] for w in wars)
    total_wars = len(wars)

    response = (
        input(
            f"\nThis will DELETE all data: {total_wars} war(s), {total_races} race(s). "
            "The database file will be preserved but emptied. (yes/no): "
        )
        .strip()
        .lower()
    )

    if response != "yes":
        print("Reset cancelled.")
        return

    persistence.reset_db()
    print("Database reset successfully. Schema recreated, all data removed.")


def main() -> None:
    """Main CLI entry point."""
    config.seed_config_files()
    try:
        args = parse_arguments()

        # Handle war management commands
        if args.list_wars:
            list_wars_cmd()
            return

        if args.delete_war is not None:
            delete_war_cmd(args.delete_war)
            return

        if args.delete_wars is not None:
            delete_wars_cmd([int(x) for x in args.delete_wars])
            return

        if args.delete_race is not None:
            war_name_arg, race_number_arg = args.delete_race
            try:
                race_number = int(race_number_arg)
            except ValueError:
                print(f"ERROR: Invalid race number: {race_number_arg}")
                sys.exit(1)
            delete_race_cmd(war_name_arg, race_number)
            return

        if args.reset_db:
            reset_db_cmd()
            return

        if args.chat:
            chat_cmd()
            return

        if args.gui:
            gui_cmd()
            return

        if args.daemon:
            daemon_cmd()
            return

        if args.daemon_stop:
            daemon_stop_cmd()
            return

        if args.feed is not None:
            feed_cmd(args.feed)
            return

        if args.list_players:
            list_players_cmd()
            return

        if args.add_player is not None:
            add_player_cmd(args.add_player)
            return

        if args.list_team_tags:
            list_team_tags_cmd()
            return

        if args.add_team_tag is not None:
            add_team_tag_cmd(args.add_team_tag)
            return

        # Handle image processing
        if args.image_path is None:
            print("ERROR: Image path required (or use --list-wars, --delete-war)")
            sys.exit(1)

        image_path = validate_image_path(args.image_path)

        # Determine war to use
        war_name = args.war
        if war_name is None:
            war_name = war_manager.load_current_war()
        else:
            # Update current war if specified
            war_manager.set_current_war(war_name)

        # Check if the war has reached the limit of races and auto-rollover if needed
        persistence.init_db()
        war_id = persistence.get_war_by_name(war_name)
        if war_id is not None:
            races_played = persistence.get_races_played(war_id)
            if races_played >= logic.RACES_PER_WAR:
                existing_wars = persistence.list_wars()
                existing_names = [w["name"] for w in existing_wars]

                # Naming strategy: increment number if name ends with number, else find next available War N
                match = re.match(r"^(.*?)\s*(\d+)$", war_name)
                if match:
                    prefix, num = match.groups()
                    next_num = int(num) + 1
                    new_war_name = f"{prefix} {next_num}".strip()
                    while new_war_name in existing_names:
                        next_num += 1
                        new_war_name = f"{prefix} {next_num}".strip()
                else:
                    base = "War"
                    num = 1
                    new_war_name = f"{base} {num}"
                    while new_war_name in existing_names:
                        num += 1
                        new_war_name = f"{base} {num}"

                print(
                    f"\nAutomatic rollover: Current war '{war_name}' reached the limit of {logic.RACES_PER_WAR} races."
                )
                print(f"Automatically switching to a new war: '{new_war_name}'")

                war_manager.set_current_war(new_war_name)
                war_name = new_war_name

        process_scoreboard(
            image_path, war_name, force=args.force, confirm_rewind=_confirm_rewind
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
