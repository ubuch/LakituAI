"""Tests for the GUI shell's window-centering math (no display needed)."""

import unittest

from lakituai.gui import app as app_mod


class CenteredPositionTests(unittest.TestCase):
    """The window opens with its center on the focused monitor's center."""

    def test_centered_on_primary(self):
        self.assertEqual(
            app_mod._centered_position((0, 0, 1920, 1080), 1100, 700),
            (410, 190),
        )

    def test_centered_on_secondary_monitor_to_the_right(self):
        self.assertEqual(
            app_mod._centered_position((1920, 0, 3840, 1080), 1100, 700),
            (2330, 190),
        )

    def test_centered_on_monitor_left_of_primary(self):
        # A monitor to the left of the primary has negative x coordinates.
        self.assertEqual(
            app_mod._centered_position((-1920, 0, 0, 1080), 1100, 700),
            (-1510, 190),
        )

    def test_odd_sized_window(self):
        self.assertEqual(
            app_mod._centered_position((0, 0, 1920, 1080), 1101, 701),
            (410, 190),
        )

    def test_window_larger_than_monitor_pins_to_origin(self):
        self.assertEqual(
            app_mod._centered_position((0, 0, 1920, 1080), 3000, 2000),
            (0, 0),
        )


if __name__ == "__main__":
    unittest.main()
