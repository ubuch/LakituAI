"""Tests for the GUI shell's window-state persistence (no display needed)."""

import json
import tempfile
import unittest
from pathlib import Path

from lakituai.gui import app as app_mod
from lakituai.runtime_paths import user_data_dir


class WindowStateTests(unittest.TestCase):
    """Save/load/parse of the remembered window position."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self._dir.name) / "window_state.json"
        self._orig = app_mod.WINDOW_STATE_PATH
        app_mod.WINDOW_STATE_PATH = self.state_path

    def tearDown(self):
        app_mod.WINDOW_STATE_PATH = self._orig
        self._dir.cleanup()

    def test_save_then_load_round_trip(self):
        app_mod._save_window_pos(333, 222)
        self.assertEqual(app_mod._load_window_pos(), (333, 222))
        self.assertTrue(self.state_path.exists())

    def test_load_returns_none_when_missing(self):
        self.assertIsNone(app_mod._load_window_pos())

    def test_load_returns_none_on_corrupt_file(self):
        self.state_path.write_text("not json{{{")
        self.assertIsNone(app_mod._load_window_pos())

    def test_load_returns_none_on_bad_values(self):
        self.state_path.write_text(json.dumps({"x": "abc", "y": None}))
        self.assertIsNone(app_mod._load_window_pos())

    def test_save_survives_unwritable_location(self):
        app_mod.WINDOW_STATE_PATH = Path("/nonexistent-root-dir/sub") / "ws.json"
        app_mod._save_window_pos(1, 2)  # must not raise
        self.assertIsNone(app_mod._load_window_pos())


class ClampTests(unittest.TestCase):
    """Saved positions are kept reachable on the current screen."""

    def test_position_within_screen_unchanged(self):
        self.assertEqual(app_mod._clamp_window_pos(100, 200, 1920, 1080), (100, 200))

    def test_off_right_edge_clamped(self):
        x, y = app_mod._clamp_window_pos(3000, 400, 1920, 1080)
        self.assertEqual(x, 1920 - 120)
        self.assertEqual(y, 400)

    def test_off_bottom_edge_clamped(self):
        x, y = app_mod._clamp_window_pos(300, 5000, 1920, 1080)
        self.assertEqual(x, 300)
        self.assertEqual(y, 1080 - 60)

    def test_negative_position_clamped_to_zero(self):
        self.assertEqual(app_mod._clamp_window_pos(-50, -80, 1920, 1080), (0, 0))

    def test_screen_smaller_than_min_keeps_zero(self):
        self.assertEqual(app_mod._clamp_window_pos(10, 10, 100, 50), (0, 0))


class WindowStatePathTests(unittest.TestCase):
    """The state file lives in the per-user data directory."""

    def test_state_path_under_user_data_dir(self):
        self.assertTrue(
            str(app_mod.WINDOW_STATE_PATH).startswith(str(user_data_dir()))
        )


if __name__ == "__main__":
    unittest.main()
