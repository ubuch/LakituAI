import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from lakituai import daemon, detect


def blank_frame(height=1080, width=1920, color=(20, 20, 20)):
    return np.full((height, width, 3), color, dtype=np.uint8)


def zone_filled_frame(fill, color=(40, 60, 200), height=1080, width=1920):
    """Full-width saturated block filling ``fill`` of the zone from the top."""

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    frame[y1 : y1 + int((y2 - y1) * fill), x1:x2] = color
    return frame


def gameplay_frame(height=1080, width=1920):
    """Scattered saturated patches in the zone (largest blob far under gate)."""

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    rng = np.random.default_rng(0)
    for _ in range(10):
        by = rng.integers(y1, y2 - 40)
        bx = rng.integers(x1, x2 - 40)
        frame[by : by + 30, bx : bx + 30] = (30, 30, 220)
    return frame


FALLING_FILLS = (0.65, 0.80, 0.90)
SETTLED_FILL = 1.0


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make_daemon(capture_frames, clock=None, **settings_kwargs):
    frames = list(capture_frames)
    settings = daemon.DaemonSettings(**settings_kwargs)
    dispatches = []
    dmn = daemon.ScoreboardDaemon(
        settings,
        capture=lambda: frames.pop(0) if frames else None,
        dispatch=lambda path: dispatches.append(path) or 0,
        clock=clock or FakeClock(),
    )
    return dmn, dispatches


class DaemonLoopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.shots = Path(self._tmp.name) / "shots"

    def _play(self, dmn, clock, frames, advance=0.5):
        results = []
        for _ in frames:
            clock.advance(advance)
            results.append(dmn.run_once())
        return results

    def test_gameplay_never_dispatches(self):
        clock = FakeClock()
        dmn, dispatches = make_daemon(
            [gameplay_frame() for _ in range(8)], clock=clock, screenshots_dir=self.shots
        )
        self._play(dmn, clock, [None] * 8)
        self.assertEqual(dispatches, [])
        self.assertEqual(dmn.processed, 0)

    def test_falling_then_settled_dispatches_once(self):
        clock = FakeClock()
        frames = [gameplay_frame()] * 2
        frames += [zone_filled_frame(f) for f in FALLING_FILLS]
        frames += [zone_filled_frame(SETTLED_FILL)] * 6
        dmn, dispatches = make_daemon(frames, clock=clock, screenshots_dir=self.shots)
        self._play(dmn, clock, [None] * len(frames))
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(dmn.processed, 1)
        path = dispatches[0]
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix, ".jpg")

    def test_falling_alone_never_dispatches(self):
        clock = FakeClock()
        frames = [zone_filled_frame(f) for f in (0.65, 0.75, 0.85, 0.70, 0.90, 0.80)]
        dmn, dispatches = make_daemon(frames, clock=clock, screenshots_dir=self.shots)
        self._play(dmn, clock, [None] * len(frames))
        self.assertEqual(dispatches, [])

    def test_cooldown_blocks_retrigger_on_same_scoreboard(self):
        clock = FakeClock()
        frames = [zone_filled_frame(SETTLED_FILL)] * 10
        dmn, dispatches = make_daemon(
            frames, clock=clock, screenshots_dir=self.shots, cooldown_s=100.0
        )
        self._play(dmn, clock, [None] * 10)
        self.assertEqual(len(dispatches), 1)

    def test_full_cycle_two_races(self):
        clock = FakeClock()
        frames = [gameplay_frame()] * 2
        frames += [zone_filled_frame(SETTLED_FILL)] * 5
        frames += [gameplay_frame()] * 2
        frames += [zone_filled_frame(SETTLED_FILL)] * 5
        dmn, dispatches = make_daemon(
            frames, clock=clock, screenshots_dir=self.shots, cooldown_s=1.0
        )
        self._play(dmn, clock, [None] * len(frames))
        self.assertEqual(len(dispatches), 2)
        self.assertEqual(dmn.processed, 2)

    def test_capture_failure_returns_none(self):
        dmn = daemon.ScoreboardDaemon(daemon.DaemonSettings(), capture=lambda: None)
        self.assertIsNone(dmn.run_once())


class DispatchTests(unittest.TestCase):
    def test_build_cli_command_ends_with_resolved_path(self):
        cmd = daemon.build_cli_command("some/path.jpg")
        self.assertEqual(cmd[-1], str(Path("some/path.jpg").resolve()))

    @patch("lakituai.daemon.build_cli_command")
    def test_dispatch_cli_returns_exit_code(self, mock_build):
        mock_build.return_value = [sys.executable, "-c", "import sys; sys.exit(3)"]
        self.assertEqual(daemon.dispatch_cli("x.jpg"), 3)

    @patch("lakituai.daemon.build_cli_command")
    def test_dispatch_cli_timeout_returns_minus_one(self, mock_build):
        mock_build.return_value = [sys.executable, "-c", "import time; time.sleep(5)"]
        self.assertEqual(daemon.dispatch_cli("x.jpg", timeout=0.3), -1)


class LockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pid_path = Path(self._tmp.name) / "daemon.pid"

    def test_acquire_rejects_second_live_daemon(self):
        self.assertTrue(daemon.acquire_lock(self.pid_path))
        self.assertFalse(daemon.acquire_lock(self.pid_path))

    def test_acquire_overwrites_stale_pid(self):
        self.pid_path.write_text("999999999")
        self.assertTrue(daemon.acquire_lock(self.pid_path))
        self.assertEqual(self.pid_path.read_text().strip(), str(__import__("os").getpid()))


class DaemonEntryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pid_path = Path(self._tmp.name) / "daemon.pid"
        self.log_path = Path(self._tmp.name) / "daemon.log"

    def test_run_daemon_main_exits_when_locked(self):
        settings = daemon.DaemonSettings(pid_path=self.pid_path, log_path=self.log_path)
        daemon.acquire_lock(self.pid_path)
        with self.assertRaises(SystemExit) as ctx:
            daemon.run_daemon_main(settings)
        self.assertEqual(ctx.exception.code, 1)

    def test_run_daemon_main_runs_until_signal(self):
        # A timer sends SIGINT shortly after startup; the daemon's own handler
        # must catch it and exit cleanly, releasing the lock.
        import os
        import signal
        import threading

        settings = daemon.DaemonSettings(
            pid_path=self.pid_path,
            log_path=self.log_path,
            poll_interval_s=0.01,
            save_captures=False,
        )
        timer = threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGINT))
        timer.start()
        try:
            daemon.run_daemon_main(settings)
        finally:
            timer.cancel()
        self.assertFalse(self.pid_path.exists())

    def test_stop_daemon_no_pid_file(self):
        self.assertEqual(daemon.stop_daemon(self.pid_path), 1)

    def test_stop_daemon_corrupt_pid_file(self):
        self.pid_path.write_text("not-a-pid")
        self.assertEqual(daemon.stop_daemon(self.pid_path), 1)

    def test_stop_daemon_stale_pid_removes_file(self):
        self.pid_path.write_text("999999999")
        self.assertEqual(daemon.stop_daemon(self.pid_path), 1)
        self.assertFalse(self.pid_path.exists())

    def test_stop_daemon_signals_live_process(self):
        import os
        import signal
        import subprocess

        # Spawn a child that writes its own pid file and waits; stopping it
        # should signal it and (cleanly or not) end it.
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os,sys,time;"
                "open(sys.argv[1],'w').write(str(os.getpid()));"
                "time.sleep(30)",
                str(self.pid_path),
            ]
        )
        # Wait until pid file exists
        for _ in range(50):
            if self.pid_path.exists():
                break
            time.sleep(0.02)
        self.assertTrue(self.pid_path.exists())
        try:
            self.assertEqual(daemon.stop_daemon(self.pid_path), 0)
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.shots = Path(self._tmp.name) / "shots"

    def test_save_screenshot_writes_jpg(self):
        dmn = daemon.ScoreboardDaemon(daemon.DaemonSettings(screenshots_dir=self.shots))
        path = dmn._save_screenshot(zone_filled_frame(1.0))
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix, ".jpg")
        self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
