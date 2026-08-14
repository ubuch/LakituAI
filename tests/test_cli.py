"""Tests for the CLI module."""

import types
import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import lakituai
from lakituai import lakitu_ai


class CLIArgumentsTests(unittest.TestCase):
    """Tests for command-line argument parsing."""

    def test_parse_arguments_with_valid_image_path(self):
        """Parsing with valid image path should work."""
        with mock.patch("sys.argv", ["prog", "path/to/image.jpg"]):
            args = lakitu_ai.parse_arguments()
            self.assertEqual(args.image_path, "path/to/image.jpg")

    def test_parse_arguments_without_image_path_fails(self):
        """Parsing without image path should fail."""
        with mock.patch("sys.argv", ["prog"]):
            with self.assertRaises(SystemExit):
                lakitu_ai.parse_arguments()

    def test_parse_arguments_with_force_flag(self):
        """--force should be parsed and default to False otherwise."""
        with mock.patch("sys.argv", ["prog", "test.jpg", "--force"]):
            args = lakitu_ai.parse_arguments()
            self.assertTrue(args.force)

        with mock.patch("sys.argv", ["prog", "test.jpg"]):
            args = lakitu_ai.parse_arguments()
            self.assertFalse(args.force)

    def test_parse_arguments_with_daemon(self):
        """--daemon should parse as a standalone command."""
        with mock.patch("sys.argv", ["prog", "--daemon"]):
            args = lakitu_ai.parse_arguments()
            self.assertTrue(args.daemon)
            self.assertIsNone(args.image_path)

    def test_parse_arguments_with_daemon_stop(self):
        """--daemon-stop should parse as a standalone command."""
        with mock.patch("sys.argv", ["prog", "--daemon-stop"]):
            args = lakitu_ai.parse_arguments()
            self.assertTrue(args.daemon_stop)

    @mock.patch("lakituai.lakitu_ai.daemon_cmd")
    def test_main_routes_daemon(self, mock_cmd):
        with mock.patch("sys.argv", ["prog", "--daemon"]):
            lakitu_ai.main()
        mock_cmd.assert_called_once_with()

    @mock.patch("lakituai.lakitu_ai.daemon_stop_cmd")
    def test_main_routes_daemon_stop(self, mock_cmd):
        with mock.patch("sys.argv", ["prog", "--daemon-stop"]):
            lakitu_ai.main()
        mock_cmd.assert_called_once_with()

    def test_parse_arguments_with_feed(self):
        """--feed should parse multiple image paths."""
        with mock.patch("sys.argv", ["prog", "--feed", "a.png", "b.png"]):
            args = lakitu_ai.parse_arguments()
            self.assertEqual(args.feed, ["a.png", "b.png"])
            self.assertIsNone(args.image_path)

    @mock.patch("lakituai.lakitu_ai.feed_cmd")
    def test_main_routes_feed(self, mock_cmd):
        with mock.patch("sys.argv", ["prog", "--feed", "a.png"]):
            lakitu_ai.main()
        mock_cmd.assert_called_once_with(["a.png"])


class CLIDuplicateDetectionTests(unittest.TestCase):
    """Tests for the rewind/duplicate detection helpers."""

    def test_seconds_since_returns_seconds(self):
        self.assertGreater(lakitu_ai._seconds_since("2020-01-01 00:00:00"), 0)

    def test_seconds_since_recent_timestamp_is_small(self):
        import datetime

        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.assertLessEqual(lakitu_ai._seconds_since(now), 5)

    def test_seconds_since_bad_timestamp_returns_none(self):
        self.assertIsNone(lakitu_ai._seconds_since("not-a-timestamp"))
        self.assertIsNone(lakitu_ai._seconds_since(None))

    def test_confirm_rewind_with_yes(self):
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch(
            "builtins.input", return_value="yes"
        ):
            self.assertTrue(lakitu_ai._confirm_rewind("rewind message"))

    def test_confirm_rewind_with_no(self):
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch(
            "builtins.input", return_value="no"
        ):
            self.assertFalse(lakitu_ai._confirm_rewind("rewind message"))

    def test_confirm_rewind_non_interactive_skips(self):
        with mock.patch("sys.stdin.isatty", return_value=False):
            self.assertFalse(lakitu_ai._confirm_rewind("rewind message"))


class CLIImageValidationTests(unittest.TestCase):
    """Tests for image path validation."""

    def setUp(self):
        """Create temporary directory for test files."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_validate_image_path_with_existing_jpg(self):
        """Validating existing JPEG should succeed."""
        image_file = self.temp_path / "test.jpg"
        image_file.touch()

        result = lakitu_ai.validate_image_path(str(image_file))

        self.assertEqual(result, image_file.resolve())

    def test_validate_image_path_with_existing_png(self):
        """Validating existing PNG should succeed."""
        image_file = self.temp_path / "test.png"
        image_file.touch()

        result = lakitu_ai.validate_image_path(str(image_file))

        self.assertEqual(result, image_file.resolve())

    def test_validate_image_path_with_nonexistent_file_fails(self):
        """Validating non-existent file should fail."""
        with self.assertRaises(FileNotFoundError):
            lakitu_ai.validate_image_path(str(self.temp_path / "nonexistent.jpg"))

    def test_validate_image_path_with_directory_fails(self):
        """Validating directory path should fail."""
        subdir = self.temp_path / "subdir"
        subdir.mkdir()

        with self.assertRaises(ValueError):
            lakitu_ai.validate_image_path(str(subdir))

    def test_validate_image_path_with_unsupported_format_fails(self):
        """Validating unsupported image format should fail."""
        bad_file = self.temp_path / "test.txt"
        bad_file.touch()

        with self.assertRaises(ValueError):
            lakitu_ai.validate_image_path(str(bad_file))

    def test_validate_image_path_accepts_multiple_formats(self):
        """Validating various image formats should succeed."""
        formats = [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]
        for fmt in formats:
            image_file = self.temp_path / f"test{fmt}"
            image_file.touch()

            result = lakitu_ai.validate_image_path(str(image_file))
            self.assertEqual(result, image_file.resolve())


class CLIRolloverTests(unittest.TestCase):
    """Tests for automatic war rollover in CLI main."""

    @mock.patch("lakituai.lakitu_ai.process_scoreboard")
    @mock.patch("lakituai.lakitu_ai.validate_image_path")
    @mock.patch("lakituai.war_manager.load_current_war")
    @mock.patch("lakituai.war_manager.set_current_war")
    @mock.patch("lakituai.persistence.init_db")
    @mock.patch("lakituai.persistence.get_war_by_name")
    @mock.patch("lakituai.persistence.get_races_played")
    @mock.patch("lakituai.persistence.list_wars")
    def test_main_does_not_rollover_when_races_below_limit(
        self,
        mock_list_wars,
        mock_get_races,
        mock_get_war_name,
        mock_init_db,
        mock_set_war,
        mock_load_war,
        mock_validate_img,
        mock_process,
    ):
        """Should not rollover when races played is below the limit."""
        mock_load_war.return_value = "War 1"
        mock_get_war_name.return_value = 1
        mock_get_races.return_value = 5  # below default 12 limit
        mock_validate_img.return_value = Path("test.jpg")

        with mock.patch("sys.argv", ["prog", "test.jpg"]):
            lakitu_ai.main()

        mock_process.assert_called_once_with(
            Path("test.jpg"), "War 1", force=False, confirm_rewind=lakitu_ai._confirm_rewind
        )
        mock_set_war.assert_not_called()

    @mock.patch("lakituai.lakitu_ai.process_scoreboard")
    @mock.patch("lakituai.lakitu_ai.validate_image_path")
    @mock.patch("lakituai.war_manager.load_current_war")
    @mock.patch("lakituai.war_manager.set_current_war")
    @mock.patch("lakituai.persistence.init_db")
    @mock.patch("lakituai.persistence.get_war_by_name")
    @mock.patch("lakituai.persistence.get_races_played")
    @mock.patch("lakituai.persistence.list_wars")
    def test_main_rollover_when_limit_reached(
        self,
        mock_list_wars,
        mock_get_races,
        mock_get_war_name,
        mock_init_db,
        mock_set_war,
        mock_load_war,
        mock_validate_img,
        mock_process,
    ):
        """Should rollover to a new war when races played reaches the limit."""
        mock_load_war.return_value = "War 1"
        mock_get_war_name.return_value = 1
        mock_get_races.return_value = 12  # at default 12 limit
        mock_list_wars.return_value = [{"war_id": 1, "name": "War 1"}]
        mock_validate_img.return_value = Path("test.jpg")

        with mock.patch("sys.argv", ["prog", "test.jpg"]):
            lakitu_ai.main()

        mock_set_war.assert_called_once_with("War 2")
        mock_process.assert_called_once_with(
            Path("test.jpg"), "War 2", force=False, confirm_rewind=lakitu_ai._confirm_rewind
        )


class CLIResetDbTests(unittest.TestCase):
    """Tests for --reset-db CLI flag."""

    def test_parse_arguments_with_reset_db(self):
        """Parsing --reset-db should set reset_db flag."""
        with mock.patch("sys.argv", ["prog", "--reset-db"]):
            args = lakitu_ai.parse_arguments()
            self.assertTrue(args.reset_db)

    @mock.patch("lakituai.lakitu_ai.persistence.reset_db")
    @mock.patch("lakituai.lakitu_ai.persistence.list_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    @mock.patch("builtins.input", return_value="yes")
    def test_reset_db_cmd_calls_reset(
        self, mock_input, mock_init_db, mock_list_wars, mock_reset_db
    ):
        """Calling reset_db_cmd with 'yes' should call persistence.reset_db."""
        mock_list_wars.return_value = [{"war_id": 1, "name": "War 1", "races_count": 5}]

        lakitu_ai.reset_db_cmd()

        mock_reset_db.assert_called_once()

    @mock.patch("lakituai.lakitu_ai.persistence.reset_db")
    @mock.patch("lakituai.lakitu_ai.persistence.list_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    @mock.patch("builtins.input", return_value="no")
    def test_reset_db_cmd_cancelled(
        self, mock_input, mock_init_db, mock_list_wars, mock_reset_db
    ):
        """Calling reset_db_cmd with 'no' should not call persistence.reset_db."""
        mock_list_wars.return_value = [{"war_id": 1, "name": "War 1", "races_count": 5}]

        lakitu_ai.reset_db_cmd()

        mock_reset_db.assert_not_called()


class CLIDeleteWarsTests(unittest.TestCase):
    """Tests for --delete-wars CLI flag."""

    def test_parse_arguments_with_delete_wars(self):
        """Parsing --delete-wars with multiple IDs should store them as a list."""
        with mock.patch("sys.argv", ["prog", "--delete-wars", "1", "2", "3"]):
            args = lakitu_ai.parse_arguments()
            self.assertEqual(args.delete_wars, ["1", "2", "3"])

    @mock.patch("lakituai.lakitu_ai.persistence.delete_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.list_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    @mock.patch("builtins.input", return_value="yes")
    def test_delete_wars_cmd_calls_persistence(
        self, mock_input, mock_init_db, mock_list_wars, mock_delete_wars
    ):
        """Calling delete_wars_cmd with valid IDs should call persistence.delete_wars."""
        mock_list_wars.return_value = [
            {"war_id": 1, "name": "War 1", "races_count": 3},
            {"war_id": 2, "name": "War 2", "races_count": 5},
        ]
        mock_delete_wars.return_value = True

        lakitu_ai.delete_wars_cmd([1, 2])

        mock_delete_wars.assert_called_once_with([1, 2])

    @mock.patch("lakituai.lakitu_ai.persistence.delete_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.list_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    @mock.patch("builtins.input", return_value="no")
    def test_delete_wars_cmd_cancelled(
        self, mock_input, mock_init_db, mock_list_wars, mock_delete_wars
    ):
        """Calling delete_wars_cmd with 'no' should not call persistence.delete_wars."""
        mock_list_wars.return_value = [
            {"war_id": 1, "name": "War 1", "races_count": 3},
        ]

        lakitu_ai.delete_wars_cmd([1])

        mock_delete_wars.assert_not_called()

    @mock.patch("lakituai.lakitu_ai.persistence.list_wars")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    def test_delete_wars_cmd_not_found_exits(self, mock_init_db, mock_list_wars):
        """Calling delete_wars_cmd with non-existent ID should exit."""
        mock_list_wars.return_value = [
            {"war_id": 1, "name": "War 1", "races_count": 3},
        ]

        with mock.patch("sys.argv", ["prog"]):
            with self.assertRaises(SystemExit):
                lakitu_ai.delete_wars_cmd([1, 999])


class CLIDeleteRaceTests(unittest.TestCase):
    """Tests for the --delete-race CLI flag."""

    def test_parse_arguments_with_delete_race(self):
        """Parsing --delete-race should store war name and race number."""
        with mock.patch("sys.argv", ["prog", "--delete-race", "War 1", "5"]):
            args = lakitu_ai.parse_arguments()
            self.assertEqual(args.delete_race, ["War 1", "5"])

    @mock.patch("lakituai.lakitu_ai.delete_race_cmd")
    def test_main_routes_delete_race(self, mock_cmd):
        with mock.patch("sys.argv", ["prog", "--delete-race", "War 1", "5"]):
            lakitu_ai.main()
        mock_cmd.assert_called_once_with("War 1", 5)

    @mock.patch("lakituai.lakitu_ai.delete_race_cmd")
    def test_main_invalid_race_number_exits(self, mock_cmd):
        with mock.patch("sys.argv", ["prog", "--delete-race", "War 1", "abc"]):
            with self.assertRaises(SystemExit):
                lakitu_ai.main()
        mock_cmd.assert_not_called()

    @mock.patch("lakituai.lakitu_ai.persistence.delete_race")
    @mock.patch("lakituai.lakitu_ai.persistence.get_race")
    @mock.patch("lakituai.lakitu_ai.persistence.get_war_by_name")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    @mock.patch("builtins.input", return_value="yes")
    def test_delete_race_cmd_calls_persistence(
        self, mock_input, mock_init_db, mock_get_war, mock_get_race, mock_delete_race
    ):
        """delete_race_cmd with 'yes' should call persistence.delete_race."""
        mock_get_war.return_value = 1
        mock_get_race.return_value = {
            "race_number": 5,
            "created_at": "2026-01-01 10:00:00",
        }
        mock_delete_race.return_value = True

        lakitu_ai.delete_race_cmd("War 1", 5)

        mock_delete_race.assert_called_once_with(1, 5)

    @mock.patch("lakituai.lakitu_ai.persistence.delete_race")
    @mock.patch("lakituai.lakitu_ai.persistence.get_race")
    @mock.patch("lakituai.lakitu_ai.persistence.get_war_by_name")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    @mock.patch("builtins.input", return_value="no")
    def test_delete_race_cmd_cancelled(
        self, mock_input, mock_init_db, mock_get_war, mock_get_race, mock_delete_race
    ):
        """delete_race_cmd with 'no' should not call persistence.delete_race."""
        mock_get_war.return_value = 1
        mock_get_race.return_value = {
            "race_number": 5,
            "created_at": "2026-01-01 10:00:00",
        }

        lakitu_ai.delete_race_cmd("War 1", 5)

        mock_delete_race.assert_not_called()

    @mock.patch("lakituai.lakitu_ai.persistence.get_war_by_name")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    def test_delete_race_cmd_war_not_found_exits(self, mock_init_db, mock_get_war):
        """delete_race_cmd with unknown war should exit."""
        mock_get_war.return_value = None

        with self.assertRaises(SystemExit):
            lakitu_ai.delete_race_cmd("Nonexistent", 1)

    @mock.patch("lakituai.lakitu_ai.persistence.get_race")
    @mock.patch("lakituai.lakitu_ai.persistence.get_war_by_name")
    @mock.patch("lakituai.lakitu_ai.persistence.init_db")
    def test_delete_race_cmd_race_not_found_exits(
        self, mock_init_db, mock_get_war, mock_get_race
    ):
        """delete_race_cmd with unknown race number should exit."""
        mock_get_war.return_value = 1
        mock_get_race.return_value = None

        with self.assertRaises(SystemExit):
            lakitu_ai.delete_race_cmd("War 1", 99)


class CLIProcessRewindTests(unittest.TestCase):
    """Tests for the rewind confirmation flow in process_scoreboard."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.resources = Path(self.temp_dir.name)

        self.row = lakitu_ai.logic.ScoreboardRowResult(
            row_number=1, points=15, ocr_text="ne PlayerA",
            normalized_text="ne PlayerA", matched_player="ne PlayerA",
            points_recipient="ne PlayerA", match_score=100.0,
            match_source="players",
        )

        self.patchers = [
            mock.patch("lakituai.lakitu_ai.persistence.init_db"),
            mock.patch(
                "lakituai.lakitu_ai.persistence.get_or_create_war", return_value=1
            ),
            mock.patch(
                "lakituai.lakitu_ai.persistence.get_last_race", return_value=None
            ),
            mock.patch("lakituai.lakitu_ai.persistence.save_race", return_value=1),
            mock.patch("lakituai.lakitu_ai.persistence.update_standings"),
            mock.patch(
                "lakituai.lakitu_ai.persistence.get_player_standings", return_value={}
            ),
            mock.patch(
                "lakituai.lakitu_ai.persistence.get_team_standings", return_value={}
            ),
            mock.patch(
                "lakituai.lakitu_ai.persistence.get_races_played", return_value=1
            ),
            mock.patch(
                "lakituai.lakitu_ai.persistence.get_next_race_number", return_value=1
            ),
            mock.patch(
                "lakituai.lakitu_ai.logic.prepare_scoreboard_rows",
                return_value=["row0"],
            ),
            mock.patch(
                "lakituai.lakitu_ai.logic.build_scoreboard_results",
                return_value=None,
            ),
            mock.patch(
                "lakituai.lakitu_ai.logic.build_race_fingerprint", return_value="fp"
            ),
            mock.patch(
                "lakituai.lakitu_ai.logic.build_team_points", return_value={"ne": 15}
            ),
            mock.patch(
                "lakituai.lakitu_ai.logic.build_net_points", return_value={"ne": 0}
            ),
            mock.patch(
                "lakituai.lakitu_ai.logic.build_player_points",
                return_value={"ne PlayerA": 15},
            ),
            mock.patch("lakituai.lakitu_ai.logic.RESOURCES_DIR", self.resources),
        ]
        self.fake_ocr = types.ModuleType("lakituai.ocr")
        self.fake_ocr.init_ocr = mock.Mock(return_value=(None, None))
        self.fake_ocr.run_ocr = mock.Mock(return_value={})
        self.patchers.append(
            mock.patch.object(lakituai, "ocr", self.fake_ocr, create=True)
        )
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

        lakitu_ai.logic.build_scoreboard_results.return_value = [self.row]

    def tearDown(self):
        self.temp_dir.cleanup()

    def _rewind_last_race(self):
        recent = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        lakitu_ai.persistence.get_last_race.return_value = {
            "race_number": 1,
            "fingerprint": "fp",
            "created_at": recent,
        }

    def test_rewind_skips_when_confirmed_false(self):
        self._rewind_last_race()

        result = lakitu_ai.process_scoreboard(
            Path("test.jpg"), "War 1", confirm_rewind=lambda m: False
        )

        self.assertIsNone(result)
        lakitu_ai.persistence.save_race.assert_not_called()

    def test_rewind_saves_when_confirmed_true(self):
        self._rewind_last_race()

        result = lakitu_ai.process_scoreboard(
            Path("test.jpg"), "War 1", confirm_rewind=lambda m: True
        )

        self.assertEqual(result, 1)
        lakitu_ai.persistence.save_race.assert_called_once()

    def test_rewind_force_saves_without_confirm(self):
        self._rewind_last_race()
        confirm = mock.Mock(return_value=True)

        result = lakitu_ai.process_scoreboard(
            Path("test.jpg"), "War 1", force=True, confirm_rewind=confirm
        )

        self.assertEqual(result, 1)
        confirm.assert_not_called()
        lakitu_ai.persistence.save_race.assert_called_once()

    def test_no_duplicate_saves(self):
        lakitu_ai.persistence.get_last_race.return_value = {
            "race_number": 1,
            "fingerprint": "different",
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
        confirm = mock.Mock(return_value=True)

        result = lakitu_ai.process_scoreboard(
            Path("test.jpg"), "War 1", confirm_rewind=confirm
        )

        self.assertEqual(result, 1)
        confirm.assert_not_called()
        lakitu_ai.persistence.save_race.assert_called_once()

    def test_old_duplicate_not_treated_as_rewind(self):
        lakitu_ai.persistence.get_last_race.return_value = {
            "race_number": 1,
            "fingerprint": "fp",
            "created_at": "2020-01-01 00:00:00",
        }
        confirm = mock.Mock(return_value=True)

        result = lakitu_ai.process_scoreboard(
            Path("test.jpg"), "War 1", confirm_rewind=confirm
        )

        self.assertEqual(result, 1)
        confirm.assert_not_called()
        lakitu_ai.persistence.save_race.assert_called_once()


if __name__ == "__main__":
    unittest.main()
