"""Background daemon: watches the screen and auto-processes scoreboards.

A *lightweight* watcher that only captures the screen, detects a
fully-appeared scoreboard, saves a screenshot and then spawns the existing
CLI as a short-lived subprocess to run OCR. The heavy model (torch/TrOCR)
only lives inside that subprocess, so the daemon itself stays at a few
hundred MB of RAM.

Detection reuses ``lakituai.detect``: the panel is a large contiguous
saturated block (gate) that must also be *complete* -- every horizontal band
saturated AND with content (edges). Both checks run on a single frame, so
the daemon captures the very first frame on which the scoreboard is fully
down; it does not need the screen to be motionless, which matters on live
video where the panel keeps animating.

The capture and dispatch steps are injected as callables so the class is
fully testable without a screen or a real subprocess.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from lakituai import config, detect, logic, runtime_paths

DEFAULT_LOG_PATH = logic.RESOURCES_DIR / "daemon.log"
DEFAULT_PID_PATH = logic.RESOURCES_DIR / "daemon.pid"
DISPATCH_TIMEOUT_S = 600.0


@dataclass
class DaemonSettings:
    """Tunable daemon parameters; defaults come from ``config/settings.json``
    via ``settings_from_config``."""

    monitor: int = 1
    poll_interval_s: float = 0.5
    gate_fraction: float = detect.DEFAULT_GATE_FRACTION
    complete_min_band: float = detect.DEFAULT_COMPLETE_MIN_BAND
    complete_min_edge: float = detect.DEFAULT_COMPLETE_MIN_EDGE
    cooldown_s: float = 90.0
    screenshots_dir: Optional[Path] = None
    log_path: Optional[Path] = DEFAULT_LOG_PATH
    pid_path: Optional[Path] = DEFAULT_PID_PATH
    save_captures: bool = True


def make_capture(monitor: int = 1) -> Callable[[], Optional[np.ndarray]]:
    """Return a callable that grabs a full BGR frame of the given monitor.

    Args:
        monitor: mss monitor index (1 = first physical monitor).

    Returns:
        Function returning a BGR numpy frame, or None on capture failure.
    """

    import mss  # lazy: keeps the daemon module importable without mss

    def capture() -> Optional[np.ndarray]:
        try:
            with mss.mss() as sct:
                mon = sct.monitors[monitor]
                shot = sct.grab(mon)
                arr = np.frombuffer(shot.raw, dtype=np.uint8).reshape(
                    shot.height, shot.width, 4
                )
                return arr[:, :, :3].copy()
        except Exception:
            return None

    return capture


def build_cli_command(image_path: str) -> list[str]:
    """Return the command that processes ``image_path`` through the CLI.

    Frozen builds run the bundled executable directly; source runs go through
    ``python -m lakituai``.
    """

    resolved = str(Path(image_path).resolve())
    if runtime_paths.is_frozen():
        return [sys.executable, resolved]
    return [sys.executable, "-m", "lakituai", resolved]


def dispatch_cli(
    image_path: str,
    logger: Optional[logging.Logger] = None,
    timeout: float = DISPATCH_TIMEOUT_S,
) -> int:
    """Run the OCR pipeline on ``image_path`` as a subprocess.

    Returns:
        Subprocess exit code, or -1 on timeout.
    """

    log = logger or _null_logger()
    cmd = build_cli_command(image_path)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.error("OCR subprocess timed out after %ss for %s", timeout, image_path)
        return -1
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or proc.stderr or "").splitlines()[-5:])
        log.warning("OCR subprocess exit=%s\n%s", proc.returncode, tail)
    return proc.returncode


def _process_alive(pid: int) -> bool:
    """Best-effort check that a pid is still running (cross-platform).

    ``os.kill(pid, 0)`` is only safe on POSIX: on Windows it *terminates* the
    target process instead of probing it, so the Windows path uses the Win32
    API (OpenProcess + GetExitCodeProcess == STILL_ACTIVE).
    """

    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock(pid_path: Path) -> bool:
    """Acquire the daemon single-instance lock.

    Creates ``pid_path`` holding our pid. Refuses when another live daemon
    already owns it; stale files (dead pid) are overwritten. The lock is
    released automatically on clean exit.

    Returns:
        True if the lock was acquired, False if another daemon is running.
    """

    pid_path = Path(pid_path)
    if pid_path.exists():
        try:
            existing = int(pid_path.read_text().strip())
        except (ValueError, OSError):
            existing = None
        if existing is not None and _process_alive(existing):
            return False

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))
    atexit.register(_release_lock, pid_path)
    return True


def _release_lock(pid_path: Path) -> None:
    try:
        if pid_path.exists() and pid_path.read_text().strip() == str(os.getpid()):
            pid_path.unlink()
    except OSError:
        pass


def _null_logger() -> logging.Logger:
    logger = logging.getLogger("lakituai.daemon-null")
    logger.addHandler(logging.NullHandler())
    return logger


class ScoreboardDaemon:
    """Poll loop driving the detect gate/complete-panel state machine.

    States: ``idle`` -> capture+dispatch (complete scoreboard) -> ``cooldown``
    -> ``wait_absent`` (the panel is still on screen after the cooldown; wait
    until it disappears) -> ``idle``. The ``wait_absent`` leg prevents a
    second capture of the same, still-visible panel when the cooldown expires.
    """

    def __init__(
        self,
        settings: DaemonSettings,
        capture: Optional[Callable[[], Optional[np.ndarray]]] = None,
        dispatch: Optional[Callable[[Path], int]] = None,
        logger: Optional[logging.Logger] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._settings = settings
        self._capture = capture or make_capture(settings.monitor)
        self._dispatch = dispatch or (lambda p: dispatch_cli(str(p), logger=logger))
        self._logger = logger or _null_logger()
        self._clock = clock
        self._state = "idle"
        self._cooldown_until = 0.0
        self.processed = 0

    def run_once(self) -> Optional[Path]:
        """Run one poll iteration.

        Returns:
            The saved screenshot path when a scoreboard was captured and
            dispatched this tick, otherwise None.
        """

        now = self._clock()

        if self._state == "cooldown":
            if now < self._cooldown_until:
                return None
            self._state = "wait_absent"

        frame = self._capture()
        if frame is None:
            return None
        return self._observe(frame, now)

    def _observe(self, frame: np.ndarray, now: float) -> Optional[Path]:
        zone = detect.crop_zone(frame)
        if not detect.is_scoreboard(
            zone,
            self._settings.gate_fraction,
            self._settings.complete_min_band,
            self._settings.complete_min_edge,
        ):
            self._state = "idle"
            return None
        if self._state == "wait_absent":
            return None
        return self._commit(frame, now)

    def _commit(self, frame: np.ndarray, now: float) -> Optional[Path]:
        path: Optional[Path] = None
        if self._settings.save_captures:
            path = self._save_screenshot(frame)
        self._state = "cooldown"
        self._cooldown_until = now + self._settings.cooldown_s

        if path is not None:
            code = self._dispatch(path)
            self.processed += 1
            self._logger.info(
                "scoreboard detected: saved %s, dispatched (exit=%s)",
                path.name,
                code,
            )
        else:
            self._logger.info("scoreboard detected but captures disabled")
        return path

    def _save_screenshot(self, frame: np.ndarray) -> Path:
        d = self._settings.screenshots_dir or logic.SCREENSHOTS_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"auto_{_next_screenshot_index(d)}.jpg"
        cv2.imwrite(str(path), frame)
        return path

    def run(self, stop_event: Optional[Callable[[], bool]] = None) -> None:
        """Run until ``stop_event()`` returns True (or forever)."""

        should_stop = stop_event or (lambda: False)
        self._logger.info("daemon starting (monitor %s)", self._settings.monitor)
        while not should_stop():
            try:
                self.run_once()
            except Exception:
                self._logger.exception("poll iteration failed")
            time.sleep(self._settings.poll_interval_s)
        self._logger.info("daemon stopped")


def _next_screenshot_index(directory: Path) -> int:
    """Next sequential ``auto_N`` screenshot number in ``directory``."""

    highest = 0
    for path in Path(directory).glob("auto_*.jpg"):
        stem = path.stem
        if stem.startswith("auto_") and stem[5:].isdigit():
            highest = max(highest, int(stem[5:]))
    return highest + 1


def _build_logger(log_path: Optional[Path], name: str = "lakituai.daemon") -> logging.Logger:
    """Return a logger writing to stderr and ``log_path`` (if given)."""

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(file_handler)
    return logger


def settings_from_config(cfg: Optional[config.GameConfig] = None) -> DaemonSettings:
    """Build daemon settings from a loaded ``GameConfig`` (or defaults)."""

    cfg = cfg or config.load_config()
    d = cfg.daemon
    return DaemonSettings(
        monitor=d.monitor,
        poll_interval_s=d.poll_interval_s,
        gate_fraction=d.gate_fraction,
        complete_min_band=d.complete_min_band,
        complete_min_edge=d.complete_min_edge,
        cooldown_s=d.cooldown_s,
    )


def run_daemon_main(settings: Optional[DaemonSettings] = None) -> None:
    """Entry point for ``--daemon``: lock, log, and run until interrupted.

    Settings are read from ``config/settings.json`` unless overridden.
    Exits with code 1 if another daemon already owns the lock.
    """

    settings = settings or settings_from_config()
    logger = _build_logger(settings.log_path)

    if not acquire_lock(settings.pid_path):
        print(f"ERROR: another LakituAI daemon is already running ({settings.pid_path})")
        sys.exit(1)
    logger.info("lock acquired (%s)", settings.pid_path)

    stop_event = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("received signal %s, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        daemon = ScoreboardDaemon(settings, logger=logger)
        daemon.run(lambda: stop_event.is_set())
    finally:
        _release_lock(settings.pid_path)
        logger.info("daemon exiting (processed %d scoreboards)", daemon.processed)


def stop_daemon(pid_path: Optional[Path] = None) -> int:
    """Terminate a running daemon read from its pid file.

    Returns:
        0 on success, 1 if there is nothing to stop.
    """

    pid_path = Path(pid_path or DEFAULT_PID_PATH)
    if not pid_path.exists():
        print("ERROR: no daemon pid file found (is the daemon running?)")
        return 1

    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        print("ERROR: corrupt daemon pid file")
        return 1

    if not _process_alive(pid):
        print("daemon is not running (stale pid file removed)")
        pid_path.unlink()
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"ERROR: could not signal daemon pid {pid}: {exc}")
        return 1
    print(f"daemon stopped (pid {pid})")
    return 0
