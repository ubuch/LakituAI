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

from lakituai import logic, ocr, persistence, war_manager


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
            "  python -m lakituai --chat"
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
        "--reset-db",
        action="store_true",
        help="Reset the database: drop all tables and recreate schema (preserves file)",
    )

    group.add_argument(
        "--chat",
        action="store_true",
        help="Start interactive AI chat session (requires Ollama)",
    )

    # War selection (only with image_path)
    parser.add_argument(
        "--war",
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
        and not args.reset_db
        and not args.chat
    ):
        parser.error(
            "Image path required "
            "(or use --list-wars, --delete-war, --delete-wars, --reset-db, --chat)"
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


def process_scoreboard(image_path: Path, war_name: str = "Default") -> None:
    """Process a scoreboard image and persist results to SQLite + JSON.

    Extracts scoreboard rows from image, runs OCR, matches players, and
    calculates race points. Results are:
    - Saved to JSON (resources/results/race_n_TAG1-TAG2_YYYY_MM_DD.json)
    - Inserted into SQLite war database (resources/war.db)
    - Printed to stdout for user feedback

    Args:
        image_path: Path to the scoreboard image.
        war_name: Name of the war (defaults to "Default").

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

        # Generate race JSON file with deterministic naming
        results_dir = logic.RESOURCES_DIR / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        # Determine race number by parsing existing race filenames
        import re

        existing = list(results_dir.glob("race_*.json"))
        max_n = 0
        for p in existing:
            m = re.match(r"race_(\d+)_", p.name)
            if m:
                try:
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
                except ValueError:
                    continue
        race_number = max_n + 1

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

        race_json = {
            "image_path": str(image_path),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "rows": [],
            "standings": {
                "player_points": logic.build_player_points(scoreboard_rows),
                "team_points": logic.build_team_points(scoreboard_rows),
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

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"ERROR processing image: {e}", file=sys.stderr)
        raise


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


def chat_cmd() -> None:
    """Start the interactive AI chat session."""
    from lakituai.chat.agents import run_chat

    run_chat()


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

        if args.reset_db:
            reset_db_cmd()
            return

        if args.chat:
            chat_cmd()
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

        process_scoreboard(image_path, war_name)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
