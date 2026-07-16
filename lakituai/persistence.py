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
) -> int:
    """Save a race and its results to database.
    
    Inserts the race metadata and all player results for that race.
    
    Args:
        war_id: ID of the war.
        race_number: Sequential race number.
        image_path: Path to the original screenshot.
        json_path: Path to the saved race JSON.
        scoreboard_rows: List of ScoreboardRowResult objects.
        db_path: Path to SQLite database.
    
    Returns:
        ID of the inserted race.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO races (war_id, race_number, image_path, json_path)
        VALUES (?, ?, ?, ?)
        """,
        (war_id, race_number, image_path, json_path),
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
       results.append({
           "war_id": row["id"],
           "name": row["name"],
           "created_at": row["created_at"],
           "races_count": row["races_count"] or 0,
           "teams": row["teams"].split(",") if row["teams"] else []
       })
    
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

    for war_id in war_ids:
        cursor.execute(
            "DELETE FROM race_results WHERE race_id IN "
            "(SELECT id FROM races WHERE war_id = ?)",
            (war_id,),
        )
        cursor.execute("DELETE FROM races WHERE war_id = ?", (war_id,))
        cursor.execute("DELETE FROM player_standings WHERE war_id = ?", (war_id,))
        cursor.execute("DELETE FROM team_standings WHERE war_id = ?", (war_id,))
        cursor.execute("DELETE FROM war WHERE id = ?", (war_id,))

    conn.commit()
    conn.close()
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

    cursor.execute("DROP TABLE IF EXISTS race_results")
    cursor.execute("DROP TABLE IF EXISTS races")
    cursor.execute("DROP TABLE IF EXISTS player_standings")
    cursor.execute("DROP TABLE IF EXISTS team_standings")
    cursor.execute("DROP TABLE IF EXISTS war")

    conn.commit()
    conn.close()

    init_db(db_path)

