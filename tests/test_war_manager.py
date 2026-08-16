"""Tests for war selection and persistence."""

import tempfile
import unittest
from pathlib import Path

from lakituai import war_manager


class WarManagerTests(unittest.TestCase):
    """Tests for war_manager module."""

    def setUp(self):
        """Point the module at a temporary config file."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_config = Path(self.temp_dir.name) / "current_war.json"
        self.original_path = war_manager.WAR_CONFIG_PATH
        war_manager.WAR_CONFIG_PATH = self.temp_config

    def tearDown(self):
        """Clean up the temp directory and restore the config path."""
        self.temp_dir.cleanup()
        war_manager.WAR_CONFIG_PATH = self.original_path

    def test_load_current_war_defaults_to_default(self):
        """Loading the current war should default to 'Default' if no config."""
        result = war_manager.load_current_war()
        self.assertEqual(result, "Default")

    def test_set_and_load_current_war(self):
        """Setting and loading the current war should persist."""
        war_manager.set_current_war("War 1")
        result = war_manager.load_current_war()
        self.assertEqual(result, "War 1")

    def test_config_file_created(self):
        """Setting the war should create the config file."""
        self.assertFalse(self.temp_config.exists())
        war_manager.set_current_war("War 2")
        self.assertTrue(self.temp_config.exists())


if __name__ == "__main__":
    unittest.main()
