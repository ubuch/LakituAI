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


if __name__ == "__main__":
    unittest.main()
