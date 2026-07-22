import unittest
import tempfile
from pathlib import Path

from lakituai import logic, config, player_management


class LogicTests(unittest.TestCase):
    def test_points_for_position_uses_mario_kart_world_table(self):
        points = [logic.points_for_position(position) for position in range(1, 13)]

        self.assertEqual(points, [15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1])

    def test_team_tag_can_be_at_start_or_end_and_use_non_ascii_characters(self):
        players = ["RK AxeeL", "ths.ne", "β-Ray", "Rayβ"]
        team_tags = ("RK", "ne", "β")

        self.assertEqual(
            [logic.extract_team_tag(player, team_tags) for player in players],
            ["RK", "ne", "β", "β"],
        )

    def test_validate_player_tags_rejects_players_without_team_tags(self):
        with self.assertRaises(ValueError):
            logic.validate_player_tags(["RK AxeeL", "NoTeam"], ("RK", "ne"))

    def test_bot_detection_matches_playable_character_names(self):
        self.assertTrue(logic.is_bot_name(logic.normalize_text("Cow")))
        self.assertTrue(logic.is_bot_name(logic.normalize_text("Toad")))
        self.assertTrue(logic.is_bot_name(logic.normalize_text("Planta Piraña")))
        self.assertFalse(logic.is_bot_name(logic.normalize_text("Co")))

    def test_fuzzy_matching_uses_previous_ocr_without_key_error(self):
        previous_ocr = {"lecturaocrmuyrara": "RK AxeeL"}

        match = logic.fuzzy_match("lecturaocrmuyrar", previous_ocr)

        self.assertEqual(match.player_name, "RK AxeeL")
        self.assertEqual(match.source, "previous_ocr")

    def test_scoreboard_results_do_not_assign_the_same_player_twice(self):
        players = ["RK ths", "ne.crr", "β-Ray"]
        ocr_results = [(1, "RK ths"), (2, "RK ths"), (3, "ne crr")]

        rows = logic.build_scoreboard_results(ocr_results, players)
        recipients = [row.points_recipient for row in rows]

        self.assertEqual(len(recipients), len(set(recipients)))

    def test_missing_player_gets_last_position_points_when_only_11_rows_exist(self):
        players = [f"RK Player{i}" for i in range(1, 7)] + [
            f"ne.Player{i}" for i in range(7, 13)
        ]
        ocr_results = [
            (position, player) for position, player in enumerate(players[:11], 1)
        ]

        rows = logic.build_scoreboard_results(ocr_results, players)
        missing_row = rows[-1]

        self.assertTrue(missing_row.is_missing_player)
        self.assertEqual(missing_row.row_number, 12)
        self.assertEqual(missing_row.points, 1)
        self.assertEqual(missing_row.points_recipient, players[11])

    def test_bot_position_points_go_to_the_missing_player(self):
        players = ["RK Alpha", "β-Ray", "ne.COOK"]
        ocr_results = [(1, "RK Alpha"), (2, "Cow"), (3, "ne.COOK")]

        rows = logic.build_scoreboard_results(ocr_results, players)
        bot_row = rows[1]

        self.assertTrue(bot_row.is_bot)
        self.assertEqual(bot_row.points, 12)
        self.assertEqual(bot_row.points_recipient, "β-Ray")

    def test_player_and_team_points_are_accumulated_across_races(self):
        players = ["RK Alpha", "β-Ray", "ne.COOK"]
        team_tags = ("RK", "β", "ne")
        race_1 = logic.build_scoreboard_results(
            [(1, "RK Alpha"), (2, "β-Ray"), (3, "ne.COOK")],
            players,
        )
        race_2 = logic.build_scoreboard_results(
            [(1, "β-Ray"), (2, "Cow"), (3, "RK Alpha")],
            players,
        )

        standings = logic.add_race_to_standings(
            race_1, players=players, team_tags=team_tags
        )
        logic.add_race_to_standings(race_2, standings, players, team_tags)

        self.assertEqual(
            standings.player_points,
            {
                "RK Alpha": 25,
                "β-Ray": 27,
                "ne.COOK": 22,
            },
        )
        self.assertEqual(
            standings.team_points,
            {
                "RK": 25,
                "β": 27,
                "ne": 22,
            },
        )
        self.assertEqual(standings.races_played, 2)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        """Create temporary directories for config files."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        """Clean up temporary directories."""
        self.temp_dir.cleanup()

    def test_load_config_returns_defaults_when_files_dont_exist(self):
        """Loading from non-existent paths should return default configuration."""
        cfg = config.load_config(
            self.temp_path / "missing_bots.json",
            self.temp_path / "missing_players.json",
            self.temp_path / "missing_team_tags.json",
        )

        self.assertEqual(cfg.bots, config.DEFAULT_BOTS)
        self.assertEqual(cfg.players, [])
        self.assertEqual(cfg.team_tags, [])

    def test_save_and_load_config_preserves_data(self):
        """Saving and loading should preserve configuration."""
        bots_path = self.temp_path / "bots.json"
        players_path = self.temp_path / "players.json"
        team_tags_path = self.temp_path / "team_tags.json"

        original_cfg = config.GameConfig(
            bots=["Mario", "Luigi"],
            players=["RK Player1", "ne.Player2"],
            team_tags=["RK", "ne"],
        )
        config.save_config(original_cfg, bots_path, players_path, team_tags_path)

        loaded_cfg = config.load_config(bots_path, players_path, team_tags_path)

        self.assertEqual(loaded_cfg.bots, ["Mario", "Luigi"])
        self.assertEqual(loaded_cfg.players, ["RK Player1", "ne.Player2"])
        self.assertEqual(loaded_cfg.team_tags, ["RK", "ne"])


class PlayerManagementTests(unittest.TestCase):
    def setUp(self):
        """Create temporary config files for testing."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.players_path = self.temp_path / "players.json"
        self.bots_path = self.temp_path / "bots.json"
        self.team_tags_path = self.temp_path / "team_tags.json"

        # Initialize with test configs
        config.save_json_list(self.players_path, ["RK Existing", "ne.Existing"])
        config.save_json_list(self.bots_path, config.DEFAULT_BOTS)
        config.save_json_list(self.team_tags_path, ["RK", "ne"])

    def tearDown(self):
        """Clean up temporary directories."""
        self.temp_dir.cleanup()

    def test_add_player_with_valid_team_tag(self):
        """Adding a player with a valid team tag should succeed."""
        success, msg = player_management.add_player(
            "RK NewPlayer",
            self.players_path,
        )

        self.assertTrue(success)
        players = player_management.get_players(self.players_path)
        self.assertIn("RK NewPlayer", players)

    def test_add_player_without_team_tag_fails(self):
        """Adding a player without a team tag should fail."""
        success, msg = player_management.add_player(
            "NoTeamPlayer",
            self.players_path,
        )

        self.assertFalse(success)
        self.assertNotIn(
            "NoTeamPlayer", player_management.get_players(self.players_path)
        )

    def test_add_duplicate_player_fails(self):
        """Adding an already existing player should fail."""
        player_management.add_player("RK NewPlayer", self.players_path)
        success, msg = player_management.add_player(
            "RK NewPlayer",
            self.players_path,
        )

        self.assertFalse(success)

    def test_remove_player_succeeds(self):
        """Removing an existing player should succeed."""
        player_management.add_player("RK ToRemove", self.players_path)
        success, msg = player_management.remove_player(
            "RK ToRemove",
            self.players_path,
        )

        self.assertTrue(success)
        self.assertNotIn(
            "RK ToRemove", player_management.get_players(self.players_path)
        )

    def test_remove_nonexistent_player_fails(self):
        """Removing a non-existent player should fail."""
        success, msg = player_management.remove_player(
            "RK NonExistent",
            self.players_path,
        )

        self.assertFalse(success)

    def test_add_bot_succeeds(self):
        """Adding a new bot should succeed."""
        success, msg = player_management.add_bot(
            "NewCharacter",
            self.bots_path,
        )

        self.assertTrue(success)
        bots = player_management.get_bots(self.bots_path)
        self.assertIn("NewCharacter", bots)

    def test_add_duplicate_bot_fails(self):
        """Adding a duplicate bot should fail."""
        player_management.add_bot("DuplicateBot", self.bots_path)
        success, msg = player_management.add_bot(
            "DuplicateBot",
            self.bots_path,
        )

        self.assertFalse(success)

    def test_remove_bot_succeeds(self):
        """Removing an existing bot should succeed."""
        player_management.add_bot("TempBot", self.bots_path)
        success, msg = player_management.remove_bot(
            "TempBot",
            self.bots_path,
        )

        self.assertTrue(success)
        self.assertNotIn("TempBot", player_management.get_bots(self.bots_path))

    def test_remove_nonexistent_bot_fails(self):
        """Removing a non-existent bot should fail."""
        success, msg = player_management.remove_bot(
            "NonExistentBot",
            self.bots_path,
        )

        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
