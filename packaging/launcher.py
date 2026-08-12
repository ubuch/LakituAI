"""PyInstaller entry point for the LakituAI desktop GUI.

When frozen, the executable launches the desktop GUI directly (there is
no CLI in the packaged product). The CLI remains available when running
from source with ``python -m lakituai``.
"""

from lakituai.lakitu_ai import gui_cmd

if __name__ == "__main__":
    gui_cmd()
