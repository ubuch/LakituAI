"""Tests for chatbot tools."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lakituai import config, persistence
from lakituai.chat import tools


def _populate_test_db(db_path):
    """Populate a temp DB with standard test data."""
    persistence.init_db(db_path)
    conn = persistence.sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("INSERT INTO war (name) VALUES (?)", ("TestWar",))
    war_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO races (war_id, race_number, json_path) VALUES (?, ?, ?)",
        (war_id, 1, "/fake/race1.json"),
    )
    race_id = cursor.lastrowid

    players = [
        ("RK AxeeL", 1, 15),
        ("ne.ths", 2, 12),
        ("RK ivanchu", 3, 10),
        ("ne.LOLmdr", 4, 9),
        ("RK Aketx", 5, 8),
        ("ne.popoff", 6, 7),
        ("ne.crr", 7, 6),
        ("RK Kevo", 8, 5),
        ("ne.KIRIO", 9, 4),
        ("RK jonz", 10, 3),
        ("ne.starlow", 11, 2),
        ("RK César", 12, 1),
    ]
    for name, pos, pts in players:
        cursor.execute(
            "INSERT INTO race_results (race_id, player_name, position, points) VALUES (?, ?, ?, ?)",
            (race_id, name, pos, pts),
        )

    for name, pos, pts in players:
        cursor.execute(
            "INSERT INTO player_standings (war_id, player_name, total_points, races_played) VALUES (?, ?, ?, 1)",
            (war_id, name, pts),
        )

    for tag in ("RK", "ne"):
        team_pts = sum(p for n, _, p in players if n.startswith(tag))
        cursor.execute(
            "INSERT INTO team_standings (war_id, team_tag, total_points, races_played) VALUES (?, ?, ?, 1)",
            (war_id, tag, team_pts),
        )

    conn.commit()
    conn.close()
    return war_id


class ResolvePlayerNameTests(unittest.TestCase):
    """Tests for resolve_player_name helper."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        _populate_test_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_match(self):
        self.assertEqual(
            tools.resolve_player_name("RK AxeeL", db_path=str(self.db_path)),
            "RK AxeeL",
        )

    def test_case_insensitive_match(self):
        self.assertEqual(
            tools.resolve_player_name("rk axeel", db_path=str(self.db_path)),
            "RK AxeeL",
        )

    def test_accent_insensitive_match(self):
        self.assertEqual(
            tools.resolve_player_name("CESAR", db_path=str(self.db_path)),
            "RK César",
        )

    def test_base_name_match(self):
        self.assertEqual(
            tools.resolve_player_name("César", db_path=str(self.db_path)),
            "RK César",
        )

    def test_no_match_returns_none(self):
        self.assertIsNone(
            tools.resolve_player_name("NobodyHere", db_path=str(self.db_path))
        )

    def test_empty_db_returns_none(self):
        empty_db = Path(self.temp_dir.name) / "empty.db"
        persistence.init_db(empty_db)
        self.assertIsNone(
            tools.resolve_player_name("AxeeL", db_path=str(empty_db))
        )


class _BaseToolTest(unittest.TestCase):
    """Base class for tool tests that need a temp DB + war."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.war_id = _populate_test_db(self.db_path)
        self._patches = []

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self.temp_dir.cleanup()

    def _patch(self, target, *args, **kwargs):
        p = mock.patch(target, *args, **kwargs)
        self._patches.append(p)
        return p.start()


class EditPlayerTests(_BaseToolTest):
    """Tests for edit_player tool."""

    def setUp(self):
        super().setUp()
        # Temp config files
        self.players_path = Path(self.temp_dir.name) / "players.json"
        self.players_path.write_text(json.dumps(["RK AxeeL", "RK César", "ne.ths"]))
        self.tags_path = Path(self.temp_dir.name) / "team_tags.json"
        self.tags_path.write_text(json.dumps(["RK", "ne"]))

        # Point DB to temp (config path is handled via load_config mock)
        self._patch("lakituai.chat.tools.persistence.DB_PATH", self.db_path)

    def test_rename_player(self):
        # Mock load_config to work with our temp files
        cfg = config.load_config(
            players_path=self.players_path,
            team_tags_path=self.tags_path,
        )
        with mock.patch("lakituai.chat.tools.config.load_config", return_value=cfg):
            with mock.patch("lakituai.chat.tools.config.save_config") as mock_save:
                result = tools.edit_player("cesar", "RK Césarito")

        self.assertIn("Renamed", result)
        self.assertIn("RK César", result)
        self.assertIn("RK Césarito", result)

        # Verify save_config was called with updated players
        mock_save.assert_called_once()
        saved_cfg = mock_save.call_args[0][0]
        self.assertIn("RK Césarito", saved_cfg.players)
        self.assertNotIn("RK César", saved_cfg.players)

        # Verify DB was updated
        conn = persistence.sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT player_name FROM race_results WHERE position = 12")
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row[0], "RK Césarito")

    def test_player_not_found_via_resolve(self):
        result = tools.edit_player("nobody", "RK New")
        self.assertEqual(result, "Player 'nobody' not found.")

    @mock.patch("lakituai.chat.tools.config.load_config")
    def test_same_name(self, mock_cfg):
        mock_cfg.return_value.players = ["RK César"]
        result = tools.edit_player("RK César", "RK César")
        self.assertIn("same as current name", result)

    @mock.patch("lakituai.chat.tools.config.load_config")
    def test_new_name_already_exists(self, mock_cfg):
        mock_cfg.return_value.players = ["RK César", "RK AxeeL"]
        result = tools.edit_player("RK César", "RK AxeeL")
        self.assertIn("already exists", result)

    @mock.patch("lakituai.chat.tools.config.load_config")
    def test_player_not_in_config(self, mock_cfg):
        mock_cfg.return_value.players = ["RK AxeeL"]
        result = tools.edit_player("RK César", "RK New")
        self.assertIn("not found in config", result)


class GetPlayerStatsTests(_BaseToolTest):
    """Tests for get_player_stats tool."""

    def setUp(self):
        super().setUp()
        self._patch("lakituai.chat.tools.persistence.DB_PATH", self.db_path)
        self._patch("lakituai.chat.tools.war_manager.load_current_war", return_value="TestWar")
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=self.war_id)

    def test_happy_path(self):
        result = tools.get_player_stats("rk axeel")
        self.assertIn("RK AxeeL", result)
        self.assertIn("15", result)
        self.assertIn("1.0", result)
        self.assertIn("P1", result)

    def test_player_not_found_via_resolve(self):
        result = tools.get_player_stats("nobody")
        self.assertIn("not found", result)

    def test_war_not_found(self):
        # Re-patch get_war_by_name to return None
        p = self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=None)
        result = tools.get_player_stats("RK AxeeL")
        self.assertIn("not found", result)

    def test_multiple_races(self):
        # Add a second race
        conn = persistence.sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO races (war_id, race_number, json_path) VALUES (?, ?, ?)",
            (self.war_id, 2, "/fake/race2.json"),
        )
        race2_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO race_results (race_id, player_name, position, points) VALUES (?, ?, ?, ?)",
            (race2_id, "RK AxeeL", 2, 12),
        )
        conn.commit()
        conn.close()

        result = tools.get_player_stats("RK AxeeL")
        self.assertIn("Races played: 2", result)
        self.assertIn("Total points: 27", result)
        self.assertIn("Avg position: 1.5", result)
        self.assertIn("P1", result)
        self.assertIn("P2", result)

    def test_no_results(self):
        # Add a second war with "RK AxeeL" so resolve still finds the player
        conn = persistence.sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO war (name) VALUES (?)", ("War2",))
        war2_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO races (war_id, race_number, json_path) VALUES (?, ?, ?)",
            (war2_id, 1, "/fake/war2_race1.json"),
        )
        race2_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO race_results (race_id, player_name, position, points) VALUES (?, ?, ?, ?)",
            (race2_id, "RK AxeeL", 1, 15),
        )
        # Now delete from the first war
        cursor.execute(
            "DELETE FROM race_results WHERE race_id IN (SELECT id FROM races WHERE war_id = ?)",
            (self.war_id,),
        )
        conn.commit()
        conn.close()

        result = tools.get_player_stats("RK AxeeL")
        self.assertIn("No results", result)


class GetTeamStatsTests(_BaseToolTest):
    """Tests for get_team_stats tool."""

    def setUp(self):
        super().setUp()
        self._patch("lakituai.chat.tools.persistence.DB_PATH", self.db_path)
        self._patch("lakituai.chat.tools.war_manager.load_current_war", return_value="TestWar")
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=self.war_id)

    def test_happy_path(self):
        result = tools.get_team_stats("RK")
        self.assertIn("Team 'RK'", result)
        self.assertIn("42", result)  # total RK points
        self.assertIn("RK AxeeL", result)  # top scorer

    def test_team_not_found(self):
        result = tools.get_team_stats("FAKE")
        self.assertIn("not found", result)

    def test_war_not_found(self):
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=None)
        result = tools.get_team_stats("RK")
        self.assertIn("not found", result)


class ComparePlayersTests(_BaseToolTest):
    """Tests for compare_players tool."""

    def setUp(self):
        super().setUp()
        self._patch("lakituai.chat.tools.persistence.DB_PATH", self.db_path)
        self._patch("lakituai.chat.tools.war_manager.load_current_war", return_value="TestWar")
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=self.war_id)

    def test_happy_path(self):
        result = tools.compare_players("RK AxeeL", "RK César")
        self.assertIn("Head-to-head", result)
        self.assertIn("RK AxeeL: 1 wins", result)
        self.assertIn("RK César: 0 wins", result)
        self.assertIn("15pts", result)
        self.assertIn("1pts", result)

    def test_player1_not_found(self):
        result = tools.compare_players("nobody", "RK AxeeL")
        self.assertIn("not found", result)

    def test_player2_not_found(self):
        result = tools.compare_players("RK AxeeL", "nobody")
        self.assertIn("not found", result)

    def test_same_player_not_found(self):
        result = tools.compare_players("nobody", "nobody")
        self.assertIn("not found", result)


class GetRaceSummaryTests(_BaseToolTest):
    """Tests for get_race_summary tool."""

    def setUp(self):
        super().setUp()
        self._patch("lakituai.chat.tools.persistence.DB_PATH", self.db_path)
        self._patch("lakituai.chat.tools.war_manager.load_current_war", return_value="TestWar")
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=self.war_id)

    def test_happy_path(self):
        result = tools.get_race_summary(1)
        self.assertIn("Race #1", result)
        self.assertIn("Winner", result)
        self.assertIn("RK AxeeL", result)
        self.assertIn("Last place", result)
        self.assertIn("RK César", result)
        self.assertIn("Closest finish", result)

    def test_race_not_found(self):
        result = tools.get_race_summary(99)
        self.assertIn("not found", result)

    def test_war_not_found(self):
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=None)
        result = tools.get_race_summary(1)
        self.assertIn("not found", result)


class GetQuickSummaryTests(_BaseToolTest):
    """Tests for get_quick_summary tool."""

    def setUp(self):
        super().setUp()
        self._patch("lakituai.chat.tools.persistence.DB_PATH", self.db_path)
        self._patch("lakituai.chat.tools.war_manager.load_current_war", return_value="TestWar")
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=self.war_id)

    def test_happy_path(self):
        result = tools.get_quick_summary()
        self.assertIn("TestWar", result)
        self.assertIn("RK: 42pts", result)
        self.assertIn("ne: 40pts", result)
        self.assertIn("Races: 1", result)
        self.assertIn("RK AxeeL", result)

    def test_war_not_found(self):
        self._patch("lakituai.chat.tools.persistence.get_war_by_name", return_value=None)
        result = tools.get_quick_summary()
        self.assertIn("not found", result)


if __name__ == "__main__":
    unittest.main()
