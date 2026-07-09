"""Tests for tournament manager module."""

import tempfile
import unittest
from pathlib import Path

from lakituai import war_manager


class TournamentManagerTests(unittest.TestCase):
    """Tests for tournament_manager module."""

    def setUp(self):
        """Set up temp config directory."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_config = Path(self.temp_dir.name) / "current_tournament.json"
        # Temporarily patch the config path
        self.original_path = war_manager.TOURNAMENT_CONFIG_PATH
        war_manager.TOURNAMENT_CONFIG_PATH = self.temp_config

    def tearDown(self):
        """Clean up temp directory and restore original config path."""
        self.temp_dir.cleanup()
        war_manager.TOURNAMENT_CONFIG_PATH = self.original_path

    def test_load_current_tournament_defaults_to_default(self):
        """Loading current tournament should default to 'Default' if no config."""
        result = war_manager.load_current_tournament()
        self.assertEqual(result, "Default")

    def test_set_and_load_current_tournament(self):
        """Setting and loading current tournament should persist."""
        war_manager.set_current_tournament("War 1")
        result = war_manager.load_current_tournament()
        self.assertEqual(result, "War 1")

    def test_get_tournament_display_name(self):
        """Display name should format tournament ID and name."""
        display = war_manager.get_tournament_display_name(1, "War 1")
        self.assertEqual(display, "#1: War 1")

    def test_config_file_created(self):
        """Setting tournament should create config file."""
        self.assertFalse(self.temp_config.exists())
        war_manager.set_current_tournament("War 2")
        self.assertTrue(self.temp_config.exists())


if __name__ == "__main__":
    unittest.main()

