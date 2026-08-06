"""Tests for the SQLite persistence layer."""

import tempfile
import unittest
from pathlib import Path

from lakituai import persistence, logic


class PersistenceTests(unittest.TestCase):
    """Tests for persistence.py module."""

    def setUp(self):
        """Create a temporary database file for testing."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tournament.db"
        persistence.init_db(self.db_path)

    def tearDown(self):
        """Clean up the temporary database file."""
        self.temp_dir.cleanup()

    def test_init_db_creates_tables(self):
        """Database initialization should create all required tables."""
        # Database was initialized in setUp, so check if file exists
        self.assertTrue(self.db_path.exists())

    def test_get_or_create_war(self):
        """Creating a war should return its ID, and retrieving it again should return the same ID."""
        war_id_1 = persistence.get_or_create_war("Test War", db_path=self.db_path)
        self.assertGreater(war_id_1, 0)

        war_id_2 = persistence.get_or_create_war("Test War", db_path=self.db_path)
        self.assertEqual(war_id_1, war_id_2)

        war_id_3 = persistence.get_or_create_war("Different War", db_path=self.db_path)
        self.assertNotEqual(war_id_1, war_id_3)

    def test_get_war_by_name(self):
        """Retrieving war by name should return the war ID or None if not found."""
        war_id = persistence.get_or_create_war("My War", db_path=self.db_path)

        found_id = persistence.get_war_by_name("My War", db_path=self.db_path)
        self.assertEqual(found_id, war_id)

        not_found = persistence.get_war_by_name("Nonexistent", db_path=self.db_path)
        self.assertIsNone(not_found)

    def test_save_race_and_results(self):
        """Saving a race and its results should store correct records in DB."""
        war_id = persistence.get_or_create_war("War 1", db_path=self.db_path)

        row1 = logic.ScoreboardRowResult(
            row_number=1,
            points=15,
            ocr_text="Player A",
            normalized_text="Player A",
            matched_player="Player A",
            points_recipient="Player A",
            match_score=100.0,
            match_source="players",
        )
        row2 = logic.ScoreboardRowResult(
            row_number=2,
            points=12,
            ocr_text="Player B",
            normalized_text="Player B",
            matched_player="Player B",
            points_recipient="Player B",
            match_score=100.0,
            match_source="players",
        )

        race_id = persistence.save_race(
            war_id=war_id,
            race_number=1,
            image_path="test.jpg",
            json_path="test.json",
            scoreboard_rows=[row1, row2],
            db_path=self.db_path,
        )
        self.assertGreater(race_id, 0)

        # Verify races played counter
        races_played = persistence.get_races_played(war_id, db_path=self.db_path)
        self.assertEqual(races_played, 1)

    def test_update_standings_and_get_standings(self):
        """Updating standings should aggregate player and team points correctly."""
        war_id = persistence.get_or_create_war("War 1", db_path=self.db_path)

        row1 = logic.ScoreboardRowResult(
            row_number=1,
            points=15,
            ocr_text="ne PlayerA",
            normalized_text="ne PlayerA",
            matched_player="ne PlayerA",
            points_recipient="ne PlayerA",
            match_score=100.0,
            match_source="players",
        )
        row2 = logic.ScoreboardRowResult(
            row_number=2,
            points=12,
            ocr_text="RK PlayerB",
            normalized_text="RK PlayerB",
            matched_player="RK PlayerB",
            points_recipient="RK PlayerB",
            match_score=100.0,
            match_source="players",
        )

        team_tags = ("ne", "RK")
        persistence.update_standings(
            war_id, [row1, row2], team_tags=team_tags, db_path=self.db_path
        )

        # Get player standings
        player_standings = persistence.get_player_standings(
            war_id, db_path=self.db_path
        )
        self.assertEqual(len(player_standings), 2)
        self.assertIn("ne PlayerA", player_standings)
        self.assertEqual(player_standings["ne PlayerA"], 15)

        # Get team standings
        team_standings = persistence.get_team_standings(war_id, db_path=self.db_path)
        self.assertEqual(len(team_standings), 2)
        self.assertIn("ne", team_standings)
        self.assertEqual(team_standings["ne"], 15)

    def test_save_race_stores_team_results(self):
        """Saving a race should store per-team points and net result."""
        war_id = persistence.get_or_create_war("War 1", db_path=self.db_path)

        row1 = logic.ScoreboardRowResult(
            row_number=1, points=15, ocr_text="ne PlayerA",
            normalized_text="ne PlayerA", matched_player="ne PlayerA",
            points_recipient="ne PlayerA", match_score=100.0, match_source="players",
        )
        row2 = logic.ScoreboardRowResult(
            row_number=2, points=12, ocr_text="RK PlayerB",
            normalized_text="RK PlayerB", matched_player="RK PlayerB",
            points_recipient="RK PlayerB", match_score=100.0, match_source="players",
        )

        persistence.save_race(
            war_id=war_id, race_number=1, image_path="test.jpg",
            json_path="test.json", scoreboard_rows=[row1, row2],
            db_path=self.db_path, team_tags=("ne", "RK"),
        )

        conn = persistence.sqlite3.connect(str(self.db_path))
        conn.row_factory = persistence.sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT team_tag, points, net_points FROM team_race_results"
        )
        rows = cursor.fetchall()
        conn.close()

        results = {row["team_tag"]: (row["points"], row["net_points"]) for row in rows}
        self.assertEqual(results, {"ne": (15, 3), "RK": (12, -3)})

    def test_save_race_without_team_tags_skips_team_results(self):
        """Races without recognizable team tags should not fail to save."""
        war_id = persistence.get_or_create_war("War 1", db_path=self.db_path)

        row1 = logic.ScoreboardRowResult(
            row_number=1, points=15, ocr_text="Player A",
            normalized_text="Player A", matched_player="Player A",
            points_recipient="Player A", match_score=100.0, match_source="players",
        )

        race_id = persistence.save_race(
            war_id=war_id, race_number=1, image_path="test.jpg",
            json_path="test.json", scoreboard_rows=[row1],
            db_path=self.db_path,
        )
        self.assertGreater(race_id, 0)

        conn = persistence.sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM team_race_results")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_list_wars(self):
        """Listing wars should return all wars with metadata."""
        war_id_1 = persistence.get_or_create_war("War A", db_path=self.db_path)
        war_id_2 = persistence.get_or_create_war("War B", db_path=self.db_path)

        wars = persistence.list_wars(db_path=self.db_path)
        self.assertEqual(len(wars), 2)

        names = [w["name"] for w in wars]
        self.assertIn("War A", names)
        self.assertIn("War B", names)

    def test_delete_war(self):
        """Deleting a war should remove it and all related data (cascade delete)."""
        war_id = persistence.get_or_create_war("War to Delete", db_path=self.db_path)

        row = logic.ScoreboardRowResult(
            row_number=1,
            points=15,
            ocr_text="ne PlayerA",
            normalized_text="ne PlayerA",
            matched_player="ne PlayerA",
            points_recipient="ne PlayerA",
            match_score=100.0,
            match_source="players",
        )

        persistence.save_race(
            war_id=war_id,
            race_number=1,
            image_path="test.jpg",
            json_path="test.json",
            scoreboard_rows=[row],
            db_path=self.db_path,
        )
        persistence.update_standings(
            war_id, [row], team_tags=("ne",), db_path=self.db_path
        )

        # Verify exists
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 1)

        # Delete
        success = persistence.delete_war(war_id, db_path=self.db_path)
        self.assertTrue(success)

        # Verify deleted
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 0)

    def test_delete_wars_bulk(self):
        """Deleting multiple wars should remove all of them in one call."""
        war_id_1 = persistence.get_or_create_war("War A", db_path=self.db_path)
        war_id_2 = persistence.get_or_create_war("War B", db_path=self.db_path)
        war_id_3 = persistence.get_or_create_war("War C", db_path=self.db_path)

        row = logic.ScoreboardRowResult(
            row_number=1,
            points=15,
            ocr_text="ne PlayerA",
            normalized_text="ne PlayerA",
            matched_player="ne PlayerA",
            points_recipient="ne PlayerA",
            match_score=100.0,
            match_source="players",
        )
        persistence.save_race(
            war_id=war_id_1,
            race_number=1,
            image_path="test.jpg",
            json_path="test.json",
            scoreboard_rows=[row],
            db_path=self.db_path,
        )
        persistence.save_race(
            war_id=war_id_2,
            race_number=1,
            image_path="test.jpg",
            json_path="test.json",
            scoreboard_rows=[row],
            db_path=self.db_path,
        )

        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 3)

        success = persistence.delete_wars([war_id_1, war_id_2], db_path=self.db_path)
        self.assertTrue(success)

        remaining = persistence.list_wars(db_path=self.db_path)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["name"], "War C")

    def test_delete_wars_returns_false_if_any_not_found(self):
        """Deleting wars with a non-existent ID should return False and delete nothing."""
        war_id_1 = persistence.get_or_create_war("War A", db_path=self.db_path)
        war_id_2 = persistence.get_or_create_war("War B", db_path=self.db_path)

        success = persistence.delete_wars([war_id_1, 9999], db_path=self.db_path)
        self.assertFalse(success)

        # Nothing should be deleted (atomic)
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 2)

    def test_delete_wars_empty_list(self):
        """Deleting an empty list should return True and do nothing."""
        success = persistence.delete_wars([], db_path=self.db_path)
        self.assertTrue(success)
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 0)

    def test_reset_db(self):
        """Resetting the DB should remove all data but preserve the file and schema."""
        war_id = persistence.get_or_create_war("War 1", db_path=self.db_path)

        row = logic.ScoreboardRowResult(
            row_number=1,
            points=15,
            ocr_text="ne PlayerA",
            normalized_text="ne PlayerA",
            matched_player="ne PlayerA",
            points_recipient="ne PlayerA",
            match_score=100.0,
            match_source="players",
        )

        persistence.save_race(
            war_id=war_id,
            race_number=1,
            image_path="test.jpg",
            json_path="test.json",
            scoreboard_rows=[row],
            db_path=self.db_path,
        )
        persistence.update_standings(
            war_id, [row], team_tags=("ne",), db_path=self.db_path
        )

        # Verify data exists
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 1)

        # Reset
        persistence.reset_db(db_path=self.db_path)

        # Verify file still exists
        self.assertTrue(self.db_path.exists())

        # Verify all data is gone
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 0)

        # Verify schema is functional (can create new data)
        new_war_id = persistence.get_or_create_war("New War", db_path=self.db_path)
        self.assertGreater(new_war_id, 0)
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 1)

    def test_reset_db_empty_database(self):
        """Resetting an empty database should not raise errors."""
        persistence.reset_db(db_path=self.db_path)
        self.assertTrue(self.db_path.exists())
        self.assertEqual(len(persistence.list_wars(db_path=self.db_path)), 0)


if __name__ == "__main__":
    unittest.main()
