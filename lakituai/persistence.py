"""SQLite persistence layer for war standings and race results.

Manages database schema, race result storage, and cumulative standings
for the war. Designed for stateless workers: each run loads standings,
updates with new race, and persists back to shared SQLite database.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from lakituai import logic

DB_PATH = logic.RESOURCES_DIR / "wars.db"


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize database schema if it doesn't exist.

    Creates tables for wars, races, race results, and standings.
    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).

    Args:
        db_path: Path to SQLite database file.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # War table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS war (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Races table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS races (
            id INTEGER PRIMARY KEY,
            war_id INTEGER NOT NULL,
            race_number INTEGER NOT NULL,
            image_path TEXT,
            json_path TEXT,
            fingerprint TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (war_id) REFERENCES war(id)
        )
    """)

    # Race results (per player per race)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS race_results (
            id INTEGER PRIMARY KEY,
            race_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            points INTEGER NOT NULL,
            position INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (race_id) REFERENCES races(id)
        )
    """)

    # Team results per race (points + net result vs best other team)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_race_results (
            id INTEGER PRIMARY KEY,
            race_id INTEGER NOT NULL,
            team_tag TEXT NOT NULL,
            points INTEGER NOT NULL,
            net_points INTEGER NOT NULL,
            FOREIGN KEY (race_id) REFERENCES races(id),
            UNIQUE (race_id, team_tag)
        )
    """)

    # Player standings (cumulative)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_standings (
            id INTEGER PRIMARY KEY,
            war_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            total_points INTEGER DEFAULT 0,
            races_played INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (war_id) REFERENCES war(id),
            UNIQUE (war_id, player_name)
        )
    """)

    # Team standings (cumulative)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_standings (
            id INTEGER PRIMARY KEY,
            war_id INTEGER NOT NULL,
            team_tag TEXT NOT NULL,
            total_points INTEGER DEFAULT 0,
            races_played INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (war_id) REFERENCES war(id),
            UNIQUE (war_id, team_tag)
        )
    """)

    conn.commit()
    conn.close()


def get_or_create_war(
    war_name: str = "Default",
    db_path: Path = DB_PATH,
) -> int:
    """Get or create a war and return its ID.

    Args:
        war_name: Name of the war.
        db_path: Path to SQLite database.

    Returns:
        War ID.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM war WHERE name = ?", (war_name,))
    result = cursor.fetchone()

    if result:
        war_id = result[0]
    else:
        cursor.execute(
            "INSERT INTO war (name) VALUES (?)",
            (war_name,),
        )
        war_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return war_id


def save_race(
    war_id: int,
    race_number: int,
    image_path: str,
    json_path: str,
    scoreboard_rows: list,
    db_path: Path = DB_PATH,
    team_tags: tuple = None,
    fingerprint: str = None,
) -> int:
    """Save a race and its results to database.

    Inserts the race metadata, all player results for that race, and the
    per-team points + net result (points minus best other team).

    Args:
        war_id: ID of the war.
        race_number: Sequential race number.
        image_path: Path to the original screenshot.
        json_path: Path to the saved race JSON.
        scoreboard_rows: List of ScoreboardRowResult objects.
        db_path: Path to SQLite database.
        team_tags: Sequence of team tag strings for extraction.
        fingerprint: Optional stable race fingerprint for rewind detection.

    Returns:
        ID of the inserted race.
    """
    if team_tags is None:
        team_tags = logic.TEAM_TAGS

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO races (war_id, race_number, image_path, json_path, fingerprint)
        VALUES (?, ?, ?, ?, ?)
        """,
        (war_id, race_number, image_path, json_path, fingerprint),
    )
    race_id = cursor.lastrowid

    for row in scoreboard_rows:
        if row.points_recipient:
            cursor.execute(
                """
                INSERT INTO race_results
                (race_id, player_name, points, position)
                VALUES (?, ?, ?, ?)
                """,
                (race_id, row.points_recipient, row.points, row.row_number),
            )

    # Store per-team results (points + net vs best other team).
    # Best-effort: races without team tags skip this without failing.
    try:
        team_points = logic.build_team_points(scoreboard_rows, team_tags)
        net_points = logic.build_net_points(team_points)
        for team, pts in team_points.items():
            cursor.execute(
                """
                INSERT INTO team_race_results (race_id, team_tag, points, net_points)
                VALUES (?, ?, ?, ?)
                """,
                (race_id, team, pts, net_points.get(team, 0)),
            )
    except ValueError:
        pass

    conn.commit()
    conn.close()
    return race_id


def update_standings(
    war_id: int,
    scoreboard_rows: list,
    team_tags: tuple = None,
    db_path: Path = DB_PATH,
) -> None:
    """Update player and team standings after a new race.

    Adds race points to existing standings or creates new rows if player/team
    hasn't participated before. Increments races_played counter.

    Args:
        war_id: ID of the war.
        scoreboard_rows: List of ScoreboardRowResult objects from the race.
        team_tags: Sequence of team tag strings for extraction.
        db_path: Path to SQLite database.
    """
    if team_tags is None:
        team_tags = logic.TEAM_TAGS

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Track distinct players and teams that participated in this race
    participating_players = set()
    participating_teams = set()

    # Update player standings
    for row in scoreboard_rows:
        if not row.points_recipient:
            continue

        player = row.points_recipient
        points = row.points
        participating_players.add(player)

        cursor.execute(
            """
            INSERT INTO player_standings
            (war_id, player_name, total_points, races_played)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(war_id, player_name) DO UPDATE SET
                total_points = total_points + ?,
                races_played = races_played + 1,
                last_updated = CURRENT_TIMESTAMP
            """,
            (war_id, player, points, points),
        )

    # Update team standings
    team_points = logic.build_team_points(scoreboard_rows, team_tags)
    for team, points in team_points.items():
        participating_teams.add(team)
        cursor.execute(
            """
            INSERT INTO team_standings
            (war_id, team_tag, total_points, races_played)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(war_id, team_tag) DO UPDATE SET
                total_points = total_points + ?,
                races_played = races_played + 1,
                last_updated = CURRENT_TIMESTAMP
            """,
            (war_id, team, points, points),
        )

    conn.commit()
    conn.close()


def get_player_standings(
    war_id: int,
    db_path: Path = DB_PATH,
) -> dict[str, int]:
    """Get cumulative player points for a war.

    Args:
        war_id: ID of the war.
        db_path: Path to SQLite database.

    Returns:
        Dict mapping player name to total points, sorted by points descending.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT player_name, total_points FROM player_standings
        WHERE war_id = ?
        ORDER BY total_points DESC
        """,
        (war_id,),
    )
    results = cursor.fetchall()
    conn.close()

    return {name: points for name, points in results}


def get_team_standings(
    war_id: int,
    db_path: Path = DB_PATH,
) -> dict[str, int]:
    """Get cumulative team points for a war.

    Args:
        war_id: ID of the war.
        db_path: Path to SQLite database.

    Returns:
        Dict mapping team tag to total points, sorted by points descending.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT team_tag, total_points FROM team_standings
        WHERE war_id = ?
        ORDER BY total_points DESC
        """,
        (war_id,),
    )
    results = cursor.fetchall()
    conn.close()

    return {tag: points for tag, points in results}


def get_player_standings_up_to(
    war_id: int,
    race_number: int,
    db_path: Path = DB_PATH,
) -> dict[str, int]:
    """Get cumulative player points for a war up to and including a race.

    Unlike get_player_standings (whole-war totals), this aggregates only the
    races with race_number <= the given one, so the standings evolve as the
    war progresses and only the last race shows the final standings.

    Args:
        war_id: ID of the war.
        race_number: Cumulative ceiling (inclusive).
        db_path: Path to SQLite database.

    Returns:
        Dict mapping player name to total points, sorted by points descending.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT rr.player_name, SUM(rr.points) AS total
        FROM race_results rr
        JOIN races r ON rr.race_id = r.id
        WHERE r.war_id = ? AND r.race_number <= ?
        GROUP BY rr.player_name
        ORDER BY total DESC
        """,
        (war_id, race_number),
    )
    results = cursor.fetchall()
    conn.close()

    return {name: points for name, points in results}


def get_team_standings_up_to(
    war_id: int,
    race_number: int,
    db_path: Path = DB_PATH,
) -> dict[str, int]:
    """Get cumulative team points for a war up to and including a race.

    Same per-race ceiling semantics as get_player_standings_up_to.

    Args:
        war_id: ID of the war.
        race_number: Cumulative ceiling (inclusive).
        db_path: Path to SQLite database.

    Returns:
        Dict mapping team tag to total points, sorted by points descending.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT tr.team_tag, SUM(tr.points) AS total
        FROM team_race_results tr
        JOIN races r ON tr.race_id = r.id
        WHERE r.war_id = ? AND r.race_number <= ?
        GROUP BY tr.team_tag
        ORDER BY total DESC
        """,
        (war_id, race_number),
    )
    results = cursor.fetchall()
    conn.close()

    return {tag: points for tag, points in results}


def get_races_played(
    war_id: int,
    db_path: Path = DB_PATH,
) -> int:
    """Get total number of races played in a war.

    Uses the races_played count from any player (all players should have same count).
    Falls back to counting rows in races table if available.

    Args:
        war_id: ID of the war.
        db_path: Path to SQLite database.

    Returns:
        Number of races.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # First try to get from races table
    cursor.execute(
        "SELECT COUNT(*) FROM races WHERE war_id = ?",
        (war_id,),
    )
    races_count = cursor.fetchone()[0]

    # If races table is empty, fall back to player standings
    if races_count == 0:
        cursor.execute(
            """
            SELECT DISTINCT races_played FROM player_standings 
            WHERE war_id = ? 
            ORDER BY races_played DESC 
            LIMIT 1
            """,
            (war_id,),
        )
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    conn.close()
    return races_count


def _remove_race_json(json_path: Optional[str]) -> None:
    """Delete a race JSON file and its per-war directory if it becomes empty."""
    if not json_path:
        return
    json_file = Path(json_path)
    if json_file.exists():
        json_file.unlink()
    try:
        json_file.parent.rmdir()
    except OSError:
        pass


def get_next_race_number(war_id: int, db_path: Path = DB_PATH) -> int:
    """Get the next race number for a war.

    Race numbers are per war: every war starts again at race #1.

    Args:
        war_id: ID of the war.
        db_path: Path to SQLite database.

    Returns:
        The next race number (max existing race number + 1).
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT MAX(race_number) FROM races WHERE war_id = ?",
        (war_id,),
    )
    row = cursor.fetchone()
    conn.close()

    return (row[0] if row and row[0] is not None else 0) + 1


def list_wars(db_path: Path = DB_PATH) -> list[dict]:
    """List all wars with metadata.

    Args:
       db_path: Path to SQLite database.

    Returns:
       List of dicts with war_id, name, created_at, races_count, teams.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
       SELECT 
           t.id,
           t.name,
           t.created_at,
           COUNT(DISTINCT r.id) as races_count,
           GROUP_CONCAT(DISTINCT ts.team_tag) as teams
       FROM war t
       LEFT JOIN races r ON t.id = r.war_id
       LEFT JOIN team_standings ts ON t.id = ts.war_id
       GROUP BY t.id
       ORDER BY t.created_at DESC
    """)

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "war_id": row["id"],
                "name": row["name"],
                "created_at": row["created_at"],
                "races_count": row["races_count"] or 0,
                "teams": row["teams"].split(",") if row["teams"] else [],
            }
        )

    conn.close()
    return results


def delete_war(war_id: int, db_path: Path = DB_PATH) -> bool:
    """Delete a war and all its associated data (cascade).

    Args:
       war_id: ID of war to delete.
       db_path: Path to SQLite database.

    Returns:
       True if deletion succeeded, False if war not found.
    """
    return delete_wars([war_id], db_path)


def delete_wars(war_ids: list[int], db_path: Path = DB_PATH) -> bool:
    """Delete multiple wars and all their associated data (cascade) in one transaction.

    Deletes DB records and associated race JSON files from disk.
    Designed for future UI multi-select deletion. All deletions happen
    atomically: if any error occurs, nothing is committed.

    Args:
        war_ids: List of war IDs to delete.
        db_path: Path to SQLite database.

    Returns:
        True if all deletions succeeded, False if any war not found.
    """
    if not war_ids:
        return True

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Verify all wars exist before deleting anything
    placeholders = ",".join("?" for _ in war_ids)
    cursor.execute(f"SELECT id FROM war WHERE id IN ({placeholders})", war_ids)
    found_ids = {row[0] for row in cursor.fetchall()}

    if found_ids != set(war_ids):
        conn.close()
        return False

    # Collect JSON paths before deleting
    json_paths = []
    for war_id in war_ids:
        cursor.execute(
            "SELECT json_path FROM races WHERE war_id = ? AND json_path IS NOT NULL",
            (war_id,),
        )
        for row in cursor.fetchall():
            json_paths.append(row[0])

    for war_id in war_ids:
        cursor.execute(
            "DELETE FROM race_results WHERE race_id IN "
            "(SELECT id FROM races WHERE war_id = ?)",
            (war_id,),
        )
        cursor.execute(
            "DELETE FROM team_race_results WHERE race_id IN "
            "(SELECT id FROM races WHERE war_id = ?)",
            (war_id,),
        )
        cursor.execute("DELETE FROM races WHERE war_id = ?", (war_id,))
        cursor.execute("DELETE FROM player_standings WHERE war_id = ?", (war_id,))
        cursor.execute("DELETE FROM team_standings WHERE war_id = ?", (war_id,))
        cursor.execute("DELETE FROM war WHERE id = ?", (war_id,))

    conn.commit()
    conn.close()

    # Delete race JSON files from disk
    for json_path_str in json_paths:
        _remove_race_json(json_path_str)

    return True


def get_war_by_name(name: str, db_path: Path = DB_PATH) -> Optional[int]:
    """Get war ID by name.

    Args:
       name: War name to search for.
       db_path: Path to SQLite database.

    Returns:
       War ID if found, None otherwise.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM war WHERE name = ?", (name,))
    result = cursor.fetchone()
    conn.close()

    return result[0] if result else None


def reset_db(db_path: Path = DB_PATH) -> None:
    """Reset the database by dropping all tables and recreating the schema.

    This preserves the database file but removes all data and recreates
    the tables from scratch. Equivalent to deleting and reinitializing
    the database without touching the file system.

    Args:
        db_path: Path to SQLite database.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS team_race_results")
    cursor.execute("DROP TABLE IF EXISTS race_results")
    cursor.execute("DROP TABLE IF EXISTS races")
    cursor.execute("DROP TABLE IF EXISTS player_standings")
    cursor.execute("DROP TABLE IF EXISTS team_standings")
    cursor.execute("DROP TABLE IF EXISTS war")

    conn.commit()
    conn.close()

    init_db(db_path)


def get_race(war_id: int, race_number: int, db_path: Path = DB_PATH) -> Optional[dict]:
    """Get a single race of a war by its race number.

    Args:
        war_id: ID of the war.
        race_number: Sequential race number.
        db_path: Path to SQLite database.

    Returns:
        Dict with race_number, image_path, json_path, fingerprint, created_at,
        or None if the race does not exist.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, race_number, image_path, json_path, fingerprint, created_at
        FROM races
        WHERE war_id = ? AND race_number = ?
        """,
        (war_id, race_number),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "race_number": row["race_number"],
        "image_path": row["image_path"],
        "json_path": row["json_path"],
        "fingerprint": row["fingerprint"],
        "created_at": row["created_at"],
    }


def delete_race(war_id: int, race_number: int, db_path: Path = DB_PATH) -> bool:
    """Delete a single race and recalculate the war standings.

    Deletes the race metadata, its player results and team results, and the
    associated race JSON file from disk. Standings are rebuilt from the
    remaining races so cumulative points stay consistent.

    Args:
        war_id: ID of the war.
        race_number: Sequential race number to delete.
        db_path: Path to SQLite database.

    Returns:
        True if the race was deleted, False if it does not exist.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, json_path FROM races WHERE war_id = ? AND race_number = ?",
        (war_id, race_number),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    race_id, json_path = row

    cursor.execute("DELETE FROM race_results WHERE race_id = ?", (race_id,))
    cursor.execute("DELETE FROM team_race_results WHERE race_id = ?", (race_id,))
    cursor.execute("DELETE FROM races WHERE id = ?", (race_id,))

    conn.commit()
    conn.close()

    _remove_race_json(json_path)

    rebuild_standings(war_id, db_path)
    return True


def rebuild_standings(war_id: int, db_path: Path = DB_PATH) -> None:
    """Recalculate player and team standings for a war from scratch.

    Recomputes cumulative points and races_played from the remaining race
    results. Called after deleting a race so the cumulative tables reflect
    exactly the races still in the database.

    Args:
        war_id: ID of the war.
        db_path: Path to SQLite database.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("DELETE FROM player_standings WHERE war_id = ?", (war_id,))
    cursor.execute("DELETE FROM team_standings WHERE war_id = ?", (war_id,))

    cursor.execute(
        """
        SELECT rr.player_name,
               SUM(rr.points) AS total_points,
               COUNT(DISTINCT rr.race_id) AS races_played
        FROM race_results rr
        JOIN races r ON rr.race_id = r.id
        WHERE r.war_id = ?
        GROUP BY rr.player_name
        """,
        (war_id,),
    )
    for player, points, races in cursor.fetchall():
        cursor.execute(
            """
            INSERT INTO player_standings
            (war_id, player_name, total_points, races_played)
            VALUES (?, ?, ?, ?)
            """,
            (war_id, player, points, races),
        )

    cursor.execute(
        """
        SELECT tr.team_tag,
               SUM(tr.points) AS total_points,
               COUNT(DISTINCT tr.race_id) AS races_played
        FROM team_race_results tr
        JOIN races r ON tr.race_id = r.id
        WHERE r.war_id = ?
        GROUP BY tr.team_tag
        """,
        (war_id,),
    )
    for team, points, races in cursor.fetchall():
        cursor.execute(
            """
            INSERT INTO team_standings
            (war_id, team_tag, total_points, races_played)
            VALUES (?, ?, ?, ?)
            """,
            (war_id, team, points, races),
        )

    conn.commit()
    conn.close()


def get_last_race(war_id: int, db_path: Path = DB_PATH) -> Optional[dict]:
    """Get the most recently saved race of a war.

    Used for rewind/duplicate detection: if a new scoreboard has the same
    fingerprint as this race and arrives shortly after, it is a duplicate.

    Args:
        war_id: ID of the war.
        db_path: Path to SQLite database.

    Returns:
        Dict with race_number, fingerprint, created_at, or None if the war
        has no races yet.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, race_number, fingerprint, created_at
        FROM races
        WHERE war_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (war_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "race_number": row["race_number"],
        "fingerprint": row["fingerprint"],
        "created_at": row["created_at"],
    }
