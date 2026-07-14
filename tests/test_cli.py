"""Tests for the CLI module."""

import unittest
import tempfile
from pathlib import Path
from unittest import mock

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
        self, mock_list_wars, mock_get_races, mock_get_war_name, mock_init_db,
        mock_set_war, mock_load_war, mock_validate_img, mock_process
    ):
        """Should not rollover when races played is below the limit."""
        mock_load_war.return_value = "War 1"
        mock_get_war_name.return_value = 1
        mock_get_races.return_value = 5  # below default 12 limit
        mock_validate_img.return_value = Path("test.jpg")
        
        with mock.patch("sys.argv", ["prog", "test.jpg"]):
            lakitu_ai.main()
            
        mock_process.assert_called_once_with(Path("test.jpg"), "War 1")
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
        self, mock_list_wars, mock_get_races, mock_get_war_name, mock_init_db,
        mock_set_war, mock_load_war, mock_validate_img, mock_process
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
        mock_process.assert_called_once_with(Path("test.jpg"), "War 2")


if __name__ == "__main__":
    unittest.main()
