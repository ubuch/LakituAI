"""Chat tools for the AI agent.

Each function is a tool the LLM can call. Type hints and docstrings are used
by the Ollama library to auto-generate JSON schemas for function calling.
"""

import json
import sqlite3
import unicodedata
from typing import Optional

from lakituai import config, persistence, player_management, war_manager


def _normalize(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(no_accents.lower().split())


def _strip_tag(name: str, team_tags: list[str]) -> str:
    """Remove leading team tag from name (e.g., 'RK César' -> 'César')."""
    for tag in sorted(team_tags, key=len, reverse=True):
        if name.lower().startswith(tag.lower()):
            rest = name[len(tag):].lstrip(" .")
            if rest:
                return rest
    return name


def resolve_player_name(query: str, db_path: Optional[str] = None) -> Optional[str]:
    """Resolve a player query to the canonical stored name.

    Matching order:
      1. Exact match
      2. Case-insensitive match
      3. Accent-insensitive + case-insensitive match
      4. Base name match (tag stripped) against stored base names

    Returns the canonical stored name or None if no match found.
    """
    persistence.init_db()
    conn = sqlite3.connect(str(db_path or persistence.DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT player_name FROM race_results")
    all_names = [row[0] for row in cursor.fetchall()]
    conn.close()

    if not all_names:
        return None

    # 1. Exact match
    for name in all_names:
        if query == name:
            return name

    # 2. Case-insensitive
    q_lower = query.lower()
    for name in all_names:
        if q_lower == name.lower():
            return name

    # 3. Accent-insensitive + case-insensitive
    q_norm = _normalize(query)
    for name in all_names:
        if q_norm == _normalize(name):
            return name

    # 4. Base name match (strip tags from both sides)
    cfg = config.load_config()
    q_base = _normalize(_strip_tag(query, cfg.team_tags))
    for name in all_names:
        stored_base = _normalize(_strip_tag(name, cfg.team_tags))
        if q_base and stored_base and q_base == stored_base:
            return name

    return None


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


def get_race_position(race_number: int, position: int, war_name: Optional[str] = None) -> str:
    """Find who finished in a specific position in a specific race.

    Args:
        race_number: Race number within the war (1-based).
        position: Position to look up (1-12).
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

    cursor.execute(
        """
        SELECT player_name, points
        FROM race_results
        WHERE race_id = ? AND position = ?
        """,
        (race["id"], position),
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        return f"No result found for position {position} in race #{race_number}."

    return f"Race #{race_number} in war '{war_name}' — P{position}: {result['player_name']} ({result['points']} pts)"


def get_player_race_result(player_name: str, race_number: int, war_name: Optional[str] = None) -> str:
    """Find what position a player finished in a specific race.

    Args:
        player_name: Player name (e.g., 'RK AxeeL', 'cesar', 'axeel').
        race_number: Race number within the war (1-based).
        war_name: War name. Uses current war if not specified.
    """
    resolved = resolve_player_name(player_name)
    if not resolved:
        return f"Player '{player_name}' not found. Use list_players to see registered players."

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

    cursor.execute(
        """
        SELECT position, points
        FROM race_results
        WHERE race_id = ? AND player_name = ?
        """,
        (race["id"], resolved),
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        return f"'{resolved}' did not participate in race #{race_number}."

    return f"{resolved} finished P{result['position']} in race #{race_number} ({result['points']} pts)"


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
        player_name: Player name (e.g., 'RK AxeeL', 'cesar', 'axeel')
    """
    resolved = resolve_player_name(player_name)
    if not resolved:
        return f"Player '{player_name}' not found. Use list_players to see registered players."

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
        (resolved,),
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        return f"No history found for player '{resolved}'."

    lines = [f"History for {resolved}:", ""]
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


def edit_player(old_name: str, new_name: str) -> str:
    """Rename a player everywhere (config JSON and database).

    Args:
        old_name: Current player name (e.g., 'RK César'). Supports flexible matching.
        new_name: New player name (e.g., 'RK Césarito'). Must include team tag.
    """
    resolved = resolve_player_name(old_name)
    if not resolved:
        return f"Player '{old_name}' not found."

    cfg = config.load_config()
    if resolved not in cfg.players:
        return f"Player '{resolved}' not found in config."

    if new_name == resolved:
        return f"New name is the same as current name ('{resolved}')."

    if new_name in cfg.players:
        return f"Player '{new_name}' already exists."

    # Update config
    updated_players = [new_name if p == resolved else p for p in cfg.players]
    cfg.players = updated_players
    config.save_config(cfg)

    # Update DB
    persistence.init_db()
    conn = sqlite3.connect(str(persistence.DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE race_results SET player_name = ? WHERE player_name = ?",
        (new_name, resolved),
    )
    cursor.execute(
        "UPDATE player_standings SET player_name = ? WHERE player_name = ?",
        (new_name, resolved),
    )
    conn.commit()
    conn.close()

    return f"Renamed '{resolved}' -> '{new_name}' (config + database updated)."


def get_player_stats(player_name: str, war_name: Optional[str] = None) -> str:
    """Get aggregate stats for a player: avg position, total points, best/worst race.

    Args:
        player_name: Player name (flexible matching).
        war_name: War name. Uses current war if not specified.
    """
    resolved = resolve_player_name(player_name)
    if not resolved:
        return f"Player '{player_name}' not found."

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
        """
        SELECT r.race_number, rr.position, rr.points
        FROM race_results rr
        JOIN races r ON rr.race_id = r.id
        WHERE r.war_id = ? AND rr.player_name = ?
        ORDER BY r.race_number
        """,
        (war_id, resolved),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"No results found for '{resolved}' in war '{war_name}'."

    positions = [row["position"] for row in rows]
    points = [row["points"] for row in rows]
    avg_pos = sum(positions) / len(positions)
    total_pts = sum(points)
    best = min(rows, key=lambda r: r["position"])
    worst = max(rows, key=lambda r: r["position"])

    lines = [
        f"Stats for {resolved} in war '{war_name}':",
        f"  Races played: {len(rows)}",
        f"  Total points: {total_pts}",
        f"  Avg position: {avg_pos:.1f}",
        f"  Best race:    P{best['position']} in race #{best['race_number']} ({best['points']} pts)",
        f"  Worst race:   P{worst['position']} in race #{worst['race_number']} ({worst['points']} pts)",
    ]

    return "\n".join(lines)


def get_team_stats(team_tag: str, war_name: Optional[str] = None) -> str:
    """Get aggregate stats for a team: total points, avg per race, top/bottom player.

    Args:
        team_tag: Team tag (e.g., 'RK', 'ne').
        war_name: War name. Uses current war if not specified.
    """
    persistence.init_db()

    if war_name is None:
        war_name = war_manager.load_current_war()

    war_id = persistence.get_war_by_name(war_name)
    if war_id is None:
        return f"War '{war_name}' not found."

    cfg = config.load_config()

    conn = sqlite3.connect(str(persistence.DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get team total from team_standings
    cursor.execute(
        "SELECT total_points, races_played FROM team_standings WHERE war_id = ? AND team_tag = ?",
        (war_id, team_tag),
    )
    team_row = cursor.fetchone()
    if not team_row:
        conn.close()
        return f"Team '{team_tag}' not found in war '{war_name}'."

    # Get individual players on this team
    cursor.execute(
        """
        SELECT rr.player_name, SUM(rr.points) as total_pts, COUNT(*) as races,
               AVG(rr.position) as avg_pos
        FROM race_results rr
        JOIN races r ON rr.race_id = r.id
        WHERE r.war_id = ?
        GROUP BY rr.player_name
        """,
        (war_id,),
    )
    all_players = cursor.fetchall()
    conn.close()

    team_players = []
    for row in all_players:
        tag = config.extract_team_tag_from_game_config(row["player_name"], cfg)
        if tag == team_tag:
            team_players.append(row)

    if not team_players:
        return f"No players found for team '{team_tag}' in war '{war_name}'."

    team_players.sort(key=lambda r: r["total_pts"], reverse=True)
    top = team_players[0]
    bottom = team_players[-1]

    lines = [
        f"Team '{team_tag}' stats in war '{war_name}':",
        f"  Total points: {team_row['total_points']}",
        f"  Races played: {team_row['races_played']}",
        f"  Players: {len(team_players)}",
        f"  Top scorer:   {top['player_name']} ({top['total_pts']} pts, avg P{top['avg_pos']:.1f})",
        f"  Lowest scorer: {bottom['player_name']} ({bottom['total_pts']} pts, avg P{bottom['avg_pos']:.1f})",
    ]

    return "\n".join(lines)


def compare_players(player1: str, player2: str, war_name: Optional[str] = None) -> str:
    """Compare two players head-to-head across all races in a war.

    Args:
        player1: First player name (flexible matching).
        player2: Second player name (flexible matching).
        war_name: War name. Uses current war if not specified.
    """
    resolved1 = resolve_player_name(player1)
    resolved2 = resolve_player_name(player2)
    if not resolved1:
        return f"Player '{player1}' not found."
    if not resolved2:
        return f"Player '{player2}' not found."

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
        """
        SELECT r.race_number, rr.player_name, rr.position, rr.points
        FROM race_results rr
        JOIN races r ON rr.race_id = r.id
        WHERE r.war_id = ? AND rr.player_name IN (?, ?)
        ORDER BY r.race_number, rr.position
        """,
        (war_id, resolved1, resolved2),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"No results found for '{resolved1}' and/or '{resolved2}' in war '{war_name}'."

    # Group by race
    races = {}
    for row in rows:
        rn = row["race_number"]
        if rn not in races:
            races[rn] = {}
        races[rn][row["player_name"]] = row

    p1_wins = 0
    p2_wins = 0
    p1_total = 0
    p2_total = 0
    lines = [f"Head-to-head: {resolved1} vs {resolved2} in war '{war_name}':", ""]

    for rn in sorted(races.keys()):
        race = races[rn]
        if resolved1 in race and resolved2 in race:
            r1, r2 = race[resolved1], race[resolved2]
            p1_total += r1["points"]
            p2_total += r2["points"]
            if r1["position"] < r2["position"]:
                winner = resolved1
                p1_wins += 1
            elif r2["position"] < r1["position"]:
                winner = resolved2
                p2_wins += 1
            else:
                winner = "TIE"
            lines.append(
                f"  Race {rn}: {resolved1} P{r1['position']} ({r1['points']}pts) vs "
                f"{resolved2} P{r2['position']} ({r2['points']}pts) -> {winner}"
            )

    lines.append("")
    lines.append(f"  {resolved1}: {p1_wins} wins, {p1_total} total pts")
    lines.append(f"  {resolved2}: {p2_wins} wins, {p2_total} total pts")

    return "\n".join(lines)


def get_race_summary(race_number: int, war_name: Optional[str] = None) -> str:
    """Get a quick summary of a race: winner, closest/biggest gap, notable performances.

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

    cursor.execute(
        """
        SELECT player_name, position, points
        FROM race_results
        WHERE race_id = ?
        ORDER BY position
        """,
        (race["id"],),
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        return f"No results for race #{race_number}."

    winner = results[0]
    last = results[-1]
    points_list = [r["points"] for r in results]
    gap = points_list[0] - points_list[-1] if len(points_list) > 1 else 0

    # Find closest finish (smallest gap between consecutive positions)
    closest_gap = float("inf")
    closest_pair = None
    for i in range(len(results) - 1):
        g = results[i]["points"] - results[i + 1]["points"]
        if g < closest_gap:
            closest_gap = g
            closest_pair = (results[i], results[i + 1])

    lines = [
        f"Race #{race_number} summary in war '{war_name}':",
        f"  Winner: {winner['player_name']} ({winner['points']} pts)",
        f"  Last place: {last['player_name']} ({last['points']} pts)",
        f"  Total gap (1st-12th): {gap} pts",
    ]

    if closest_pair:
        lines.append(
            f"  Closest finish: {closest_pair[0]['player_name']} P{closest_pair[0]['position']} "
            f"vs {closest_pair[1]['player_name']} P{closest_pair[1]['position']} "
            f"({closest_gap} pts apart)"
        )

    return "\n".join(lines)


def get_race_net_result(race_number: int, war_name: Optional[str] = None) -> str:
    """Get the per-team points and net result of a race (e.g., 'RK +2', 'ne -2').

    Net result is each team's points minus the best points scored by any
    other team in the race.

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

    cursor.execute(
        """
        SELECT team_tag, points, net_points
        FROM team_race_results
        WHERE race_id = ?
        ORDER BY points DESC
        """,
        (race["id"],),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return (
            f"No team data for race #{race_number} (the race may have no "
            "players with team tags)."
        )

    lines = [f"Race #{race_number} team result in war '{war_name}':", ""]
    for row in rows:
        sign = "+" if row["net_points"] >= 0 else ""
        lines.append(
            f"  {row['team_tag']:10s}: {row['points']:3d} pts ({sign}{row['net_points']})"
        )

    return "\n".join(lines)


def get_quick_summary(war_name: Optional[str] = None) -> str:
    """Get a quick overview of a war: teams, leader, race count.

    Args:
        war_name: War name. Uses current war if not specified.
    """
    persistence.init_db()

    if war_name is None:
        war_name = war_manager.load_current_war()

    war_id = persistence.get_war_by_name(war_name)
    if war_id is None:
        return f"War '{war_name}' not found."

    races_played = persistence.get_races_played(war_id)
    player_standings = persistence.get_player_standings(war_id)
    team_standings = persistence.get_team_standings(war_id)

    if not player_standings:
        return f"War '{war_name}' has no race data yet."

    leader = max(player_standings, key=player_standings.get)
    leader_pts = player_standings[leader]
    total_players = len(player_standings)

    lines = [f"War '{war_name}' summary:", ""]

    # Teams
    if team_standings:
        teams_str = " vs ".join(
            f"{tag}: {pts}pts" for tag, pts in team_standings.items()
        )
        lines.append(f"  Teams: {teams_str}")

    lines.append(f"  Races: {races_played}")
    lines.append(f"  Players: {total_players}")
    lines.append(f"  Leader: {leader} ({leader_pts} pts)")

    return "\n".join(lines)


ALL_TOOLS = [
    list_players,
    add_player,
    remove_player,
    edit_player,
    list_team_tags,
    add_team_tag,
    remove_team_tag,
    get_standings,
    get_race_details,
    get_race_position,
    get_player_race_result,
    list_wars,
    get_player_history,
    get_player_stats,
    get_team_stats,
    compare_players,
    get_race_summary,
    get_race_net_result,
    get_quick_summary,
]
