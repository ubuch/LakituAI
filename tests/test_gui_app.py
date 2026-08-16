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
    """Saved positions are kept reachable on the current desktop."""

    def test_position_within_desktop_unchanged(self):
        self.assertEqual(
            app_mod._clamp_window_pos(100, 200, 0, 0, 1920, 1080), (100, 200)
        )

    def test_off_right_edge_clamped(self):
        x, y = app_mod._clamp_window_pos(3000, 400, 0, 0, 1920, 1080)
        self.assertEqual(x, 1920 - 120)
        self.assertEqual(y, 400)

    def test_off_bottom_edge_clamped(self):
        x, y = app_mod._clamp_window_pos(300, 5000, 0, 0, 1920, 1080)
        self.assertEqual(x, 300)
        self.assertEqual(y, 1080 - 60)

    def test_negative_position_clamped_to_left_edge(self):
        self.assertEqual(app_mod._clamp_window_pos(-50, -80, 0, 0, 1920, 1080), (0, 0))

    def test_desktop_smaller_than_min_keeps_left_edge(self):
        self.assertEqual(
            app_mod._clamp_window_pos(10, 10, 0, 0, 100, 50), (0, 0)
        )

    def test_left_monitor_negative_bounds_kept(self):
        # A monitor to the left of the primary has negative x coordinates.
        x, y = app_mod._clamp_window_pos(-1500, 300, -1920, 0, 0, 1080)
        self.assertEqual(x, -1500)
        self.assertEqual(y, 300)

    def test_off_left_of_negative_desktop_clamped_to_left_edge(self):
        x, y = app_mod._clamp_window_pos(-3000, 300, -1920, 0, 0, 1080)
        self.assertEqual(x, -1920)
        self.assertEqual(y, 300)


class SingleMonitorTests(unittest.TestCase):
    """A position is only restorable when it lies on exactly one monitor."""

    RECTS = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]

    def test_interior_point_on_single_monitor(self):
        self.assertEqual(
            app_mod._single_monitor_rect(self.RECTS, 100, 100),
            (0, 0, 1920, 1080),
        )

    def test_seam_between_side_by_side_monitors_rejected(self):
        # The classic "opened between two monitors" stale position: the point
        # is on the shared border and must not be treated as a valid restore.
        self.assertIsNone(app_mod._single_monitor_rect(self.RECTS, 1920, 540))

    def test_seam_between_stacked_monitors_rejected(self):
        rects = [(0, 0, 1920, 1080), (0, 1080, 1920, 2160)]
        self.assertIsNone(app_mod._single_monitor_rect(rects, 960, 1080))

    def test_off_screen_point_rejected(self):
        self.assertIsNone(app_mod._single_monitor_rect(self.RECTS, 4000, 500))
        self.assertIsNone(app_mod._single_monitor_rect(self.RECTS, -100, 500))

    def test_negative_coordinate_monitor(self):
        rects = [(-1920, 0, 0, 1080), (0, 0, 1920, 1080)]
        self.assertEqual(
            app_mod._single_monitor_rect(rects, -500, 500),
            (-1920, 0, 0, 1080),
        )


class WindowStatePathTests(unittest.TestCase):
    """The state file lives in the per-user data directory."""

    def test_state_path_under_user_data_dir(self):
        self.assertTrue(
            str(app_mod.WINDOW_STATE_PATH).startswith(str(user_data_dir()))
        )


if __name__ == "__main__":
    unittest.main()
