"""Runtime path resolution for source and frozen (PyInstaller) modes.

When running from source, data lives inside the repository (``config/``,
``resources/``, ``assets/``). When frozen into a standalone executable,
read-only bundled files are unpacked into ``sys._MEIPASS`` while user
data must live in a per-user writable directory (so it survives updates
and works even when installed under ``Program Files``).
"""

import os
import sys
from pathlib import Path

APP_NAME = "LakituAI"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory where read-only bundled files are unpacked at runtime."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Per-user writable data directory.

    In frozen mode this is a dedicated per-user folder; in source mode it
    falls back to the repository root so development data keeps living in
    ``config/`` and ``resources/``.
    """
    if is_frozen():
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = base / APP_NAME
    else:
        path = Path(__file__).resolve().parent.parent
    path.mkdir(parents=True, exist_ok=True)
    return path


def assets_dir() -> Path:
    """Directory containing read-only image assets (logo, icons, etc.)."""
    if is_frozen():
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent / "gui" / "assets"
