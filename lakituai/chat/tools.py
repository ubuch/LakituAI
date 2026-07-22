"""Chat tools for the AI agent.

Each function is a tool the LLM can call. Type hints and docstrings are used
by the Ollama library to auto-generate JSON schemas for function calling.
"""

import json
import sqlite3
from typing import Optional

from lakituai import config, persistence, player_management, war_manager


def list_players() -> str:
    """List all registered players with their team tags."""
    cfg = config.load_config()
    if not cfg.players:
        return "No players registered. Use add_player to add players."

    lines = []
    for player in cfg.players:
        tag = config.extract_team_tag_from_game_config(player, cfg) or "?"
        lines.append(f"  [{tag}] {player}")

    return f"Players ({len(cfg.players)}):\n" + "\n".join(lines)


def list_team_tags() -> str:
    """List all registered team tags."""
    cfg = config.load_config()
    if not cfg.team_tags:
        return "No team tags configured. Use add_team_tag to add tags first."

    return f"Team tags ({len(cfg.team_tags)}): {', '.join(cfg.team_tags)}"


def add_team_tag(tag: str) -> str:
    """Add a new team tag.

    Team tags are short identifiers prefixed or suffixed to player names
    (e.g., 'RK', 'ne'). Must be configured before adding players.

    Args:
        tag: Team tag to add (e.g., 'RK', 'ne')
    """
    cfg = config.load_config()

    if tag in cfg.team_tags:
        return f"Team tag '{tag}' already exists."

    updated_tags = list(cfg.team_tags) + [tag]
    cfg.team_tags = updated_tags
    config.save_config(cfg)
    return f"Team tag '{tag}' added. Current tags: {', '.join(cfg.team_tags)}"


def remove_team_tag(tag: str) -> str:
    """Remove a team tag.

    Args:
        tag: Team tag to remove exactly as it appears (e.g., 'RK', 'ne')
    """
    cfg = config.load_config()

    if tag not in cfg.team_tags:
        return f"Team tag '{tag}' not found."

    updated_tags = [t for t in cfg.team_tags if t != tag]
    cfg.team_tags = updated_tags
    config.save_config(cfg)
    return f"Team tag '{tag}' removed. Current tags: {', '.join(cfg.team_tags) if cfg.team_tags else '(none)'}"


def add_player(name: str, team_tag: str) -> str:
    """Add a new player to the roster.

    Args:
        name: Player name (e.g., 'ths')
        team_tag: Team tag prefix (e.g., 'ne', 'RK')
    """
    full_name = f"{team_tag} {name}"
    success, msg = player_management.add_player(full_name)
    return msg


def remove_player(name: str) -> str:
    """Remove a player from the roster.

    Args:
        name: Player name exactly as it appears in the list (e.g., 'RK AxeeL')
    """
    success, msg = player_management.remove_player(name)
    return msg


def get_standings(war_name: Optional[str] = None) -> str:
    """Get current war standings (player and team points).

    Args:
        war_name: War name. Uses current war if not specified.
    """
    persistence.init_db()

    if war_name is None:
        war_name = war_manager.load_current_war()

    war_id = persistence.get_war_by_name(war_name)
    if war_id is None:
        return f"War '{war_name}' not found."

    player_standings = persistence.get_player_standings(war_id)
    team_standings = persistence.get_team_standings(war_id)
    races_played = persistence.get_races_played(war_id)

    lines = [f"War: {war_name} | Races played: {races_played}", ""]

    lines.append("TEAM STANDINGS:")
    for team, points in team_standings.items():
        lines.append(f"  {team:10s}: {points:3d}")

    lines.append("")
    lines.append("PLAYER STANDINGS:")
    for player, points in player_standings.items():
        lines.append(f"  {player:20s}: {points:3d}")

    return "\n".join(lines)


def get_race_details(race_number: int, war_name: Optional[str] = None) -> str:
    """Get detailed results of a specific race (positions and points per player).

    Args:
        race_number: Race number within the war (1-based).
        war_name: War name. Uses current war if not specified.
    """
    persistence.init_db()

    if war_name is None:
        war_name = war_manager.load_current_war()

    war_id = persistence.get_war_by_name(war_name)
    if war_id is None:
        return f"War '{war_name}' not found."

    conn = sqlite3.connect(str(persistence.DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM races WHERE war_id = ? AND race_number = ?",
        (war_id, race_number),
    )
    race = cursor.fetchone()
    if not race:
        conn.close()
        return f"Race #{race_number} not found in war '{war_name}'."

    race_id = race["id"]
    cursor.execute(
        """
        SELECT player_name, position, points
        FROM race_results
        WHERE race_id = ?
        ORDER BY position
        """,
        (race_id,),
    )
    results = cursor.fetchall()
    conn.close()

    lines = [f"Race #{race_number} in war '{war_name}':", ""]
    for row in results:
        lines.append(f"  P{row['position']:2d}  {row['points']:2d}pts  {row['player_name']}")

    return "\n".join(lines)


def list_wars() -> str:
    """List all wars with their metadata (teams, races, date)."""
    persistence.init_db()
    wars = persistence.list_wars()

    if not wars:
        return "No wars found."

    lines = []
    for w in wars:
        teams = ", ".join(w["teams"]) if w["teams"] else "none"
        lines.append(
            f"  #{w['war_id']}: {w['name']} | "
            f"Races: {w['races_count']} | Teams: {teams} | "
            f"Created: {w['created_at']}"
        )

    return f"Wars ({len(wars)}):\n" + "\n".join(lines)


def get_player_history(player_name: str) -> str:
    """Get a player's race-by-race history across all wars.

    Args:
        player_name: Player name exactly as it appears (e.g., 'RK AxeeL')
    """
    persistence.init_db()

    conn = sqlite3.connect(str(persistence.DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT w.name AS war_name, r.race_number, rr.position, rr.points
        FROM race_results rr
        JOIN races r ON rr.race_id = r.id
        JOIN war w ON r.war_id = w.id
        WHERE rr.player_name = ?
        ORDER BY w.name, r.race_number
        """,
        (player_name,),
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        return f"No history found for player '{player_name}'."

    lines = [f"History for {player_name}:", ""]
    current_war = None
    total_points = 0

    for row in results:
        if row["war_name"] != current_war:
            current_war = row["war_name"]
            lines.append(f"  War: {current_war}")
        lines.append(
            f"    Race {row['race_number']:2d}: P{row['position']:2d} "
            f"({row['points']:2d} pts)"
        )
        total_points += row["points"]

    lines.append("")
    lines.append(f"Total points: {total_points}")

    return "\n".join(lines)


ALL_TOOLS = [
    list_players,
    add_player,
    remove_player,
    list_team_tags,
    add_team_tag,
    remove_team_tag,
    get_standings,
    get_race_details,
    list_wars,
    get_player_history,
]
