"""Tests for the Screenshots and Daemon GUI tabs (pure helpers only)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lakituai.gui import daemon_tab, screenshots_tab


class ScreenshotsHelpersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_list_screenshots_empty_when_dir_missing(self):
        self.assertEqual(screenshots_tab.list_screenshots(self.dir / "missing"), [])

    def test_list_screenshots_sorts_newest_first(self):
        old = self.dir / "auto_1.jpg"
        new = self.dir / "auto_2.png"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        self.assertEqual(screenshots_tab.list_screenshots(self.dir), [new, old])

    def test_list_screenshots_ignores_non_images(self):
        (self.dir / "notes.txt").write_text("hi")
        img = self.dir / "auto_1.jpg"
        img.write_bytes(b"x")
        self.assertEqual(screenshots_tab.list_screenshots(self.dir), [img])

    def test_parse_caption_from_name(self):
        p = Path("auto_20260814_161500123456.jpg")
        self.assertEqual(screenshots_tab.parse_caption(p), "2026-08-14 16:15:00")

    def test_parse_caption_numbered_includes_mtime(self):
        f = self.dir / "auto_7.jpg"
        f.write_bytes(b"x")
        caption = screenshots_tab.parse_caption(f)
        self.assertTrue(caption.startswith("Screenshot 7 - "))

    def test_parse_caption_falls_back_to_mtime(self):
        f = self.dir / "whatever.png"
        f.write_bytes(b"x")
        self.assertTrue(screenshots_tab.parse_caption(f))

    def test_fit_size_preserves_aspect_ratio(self):
        self.assertEqual(screenshots_tab.fit_size(1920, 1080, 800, 700), (800, 450))

    def test_fit_size_never_upscales(self):
        self.assertEqual(screenshots_tab.fit_size(100, 50, 2000, 2000), (100, 50))

    def test_fit_size_height_bound(self):
        self.assertEqual(screenshots_tab.fit_size(1920, 1080, 100, 50), (88, 50))


class DaemonHelpersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    @mock.patch("lakituai.gui.daemon_tab.runtime_paths.is_frozen", return_value=False)
    def test_build_command_source(self, _):
        self.assertEqual(
            daemon_tab.build_daemon_command(),
            [sys.executable, "-m", "lakituai", "--daemon"],
        )

    @mock.patch("lakituai.gui.daemon_tab.runtime_paths.is_frozen", return_value=True)
    def test_build_command_frozen(self, _):
        self.assertEqual(daemon_tab.build_daemon_command(), [sys.executable, "--daemon"])

    def test_daemon_running_no_pid_file(self):
        with mock.patch(
            "lakituai.gui.daemon_tab.daemon.DEFAULT_PID_PATH", self.dir / "daemon.pid"
        ):
            self.assertFalse(daemon_tab.daemon_running())

    def test_daemon_running_stale_pid(self):
        pid_path = self.dir / "daemon.pid"
        pid_path.write_text("99999999")  # almost certainly not alive
        with mock.patch(
            "lakituai.gui.daemon_tab.daemon.DEFAULT_PID_PATH", pid_path
        ):
            self.assertFalse(daemon_tab.daemon_running())

    def test_daemon_running_corrupt_pid(self):
        pid_path = self.dir / "daemon.pid"
        pid_path.write_text("not-a-number")
        with mock.patch(
            "lakituai.gui.daemon_tab.daemon.DEFAULT_PID_PATH", pid_path
        ):
            self.assertFalse(daemon_tab.daemon_running())

    def test_daemon_running_live_pid(self):
        pid_path = self.dir / "daemon.pid"
        pid_path.write_text(str(os.getpid()))
        with mock.patch(
            "lakituai.gui.daemon_tab.daemon.DEFAULT_PID_PATH", pid_path
        ):
            self.assertTrue(daemon_tab.daemon_running())


if __name__ == "__main__":
    unittest.main()
