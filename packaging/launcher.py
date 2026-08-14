"""PyInstaller entry point for the LakituAI desktop app.

Behavior depends on the arguments:
- No arguments: launch the desktop GUI.
- Any other arguments (image path, --chat, --daemon, ...): run the CLI
  entry point, so the bundled executable can be spawned by the daemon to
  run OCR on a saved screenshot.

Because the build is windowed (``console=False``), ``sys.stdout``/``stderr``
are ``None``; the CLI prints a lot, so redirect them to a per-user log file
to avoid crashes and keep a record of background OCR runs.
"""

import os
import sys

from lakituai import runtime_paths
from lakituai.lakitu_ai import gui_cmd, main


def _redirect_standard_streams() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = runtime_paths.user_data_dir() / "resources"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = open(log_dir / "cli.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


if __name__ == "__main__":
    _redirect_standard_streams()
    if len(sys.argv) > 1:
        main()
    else:
        gui_cmd()
