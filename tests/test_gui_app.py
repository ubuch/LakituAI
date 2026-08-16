"""Tests for the GUI shell's window-centering math (no display needed)."""

import unittest

from lakituai.gui import app as app_mod


class CenterOnScreenTests(unittest.TestCase):
    """The window opens centered on the screen reported by Tk."""

    def test_centered_on_1080p(self):
        self.assertEqual(
            app_mod._center_on_screen(1920, 1080, 1100, 700),
            (410, 190),
        )

    def test_centered_on_720p(self):
        self.assertEqual(
            app_mod._center_on_screen(1280, 720, 1100, 700),
            (90, 10),
        )

    def test_odd_sized_window(self):
        self.assertEqual(
            app_mod._center_on_screen(1920, 1080, 1101, 701),
            (409, 189),
        )

    def test_window_larger_than_screen_clamps_to_origin(self):
        self.assertEqual(
            app_mod._center_on_screen(1920, 1080, 3000, 2000),
            (0, 0),
        )

    def test_window_exactly_screen_size(self):
        self.assertEqual(
            app_mod._center_on_screen(1920, 1080, 1920, 1080),
            (0, 0),
        )


if __name__ == "__main__":
    unittest.main()
