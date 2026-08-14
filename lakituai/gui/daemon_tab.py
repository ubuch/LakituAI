"""Daemon tab for the LakituAI GUI.

Lets the user start and stop the background scoreboard watcher straight from
the app and shows whether it is currently running. Starting spawns the daemon
as a separate process (``--daemon``); stopping uses the pid file the same way
``--daemon-stop`` does.
"""

import os
import subprocess
import sys

import customtkinter
from PIL import Image

from lakituai import daemon, runtime_paths
from lakituai.gui.screenshots_tab import fit_size

POLL_MS = 2000
LOGO_BOX = (300, 200)
RUNNING_COLOR = ("#2e7d32", "#8bc34a")
STOPPED_COLOR = ("gray40", "gray60")


def build_daemon_command() -> list[str]:
    """Command that launches the daemon (source runs or frozen exe)."""

    if runtime_paths.is_frozen():
        return [sys.executable, "--daemon"]
    return [sys.executable, "-m", "lakituai", "--daemon"]


def daemon_running() -> bool:
    """True when a live daemon process owns the pid file."""

    pid_path = daemon.DEFAULT_PID_PATH
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False
    return daemon._process_alive(pid)


class DaemonTab(customtkinter.CTkFrame):
    """Start/stop the daemon and show its status."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._build()
        self._refresh_status()
        self.after(POLL_MS, self._poll)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)

        self.logo_label = customtkinter.CTkLabel(self, text="")
        self.logo_label.grid(row=1, column=0, pady=(30, 0))

        self.title_label = customtkinter.CTkLabel(
            self,
            text="LakituAI",
            font=customtkinter.CTkFont(size=36, weight="bold"),
        )
        self.title_label.grid(row=2, column=0, pady=(6, 2))

        self.status_label = customtkinter.CTkLabel(
            self,
            text="● Stopped",
            font=customtkinter.CTkFont(size=14),
            text_color=STOPPED_COLOR,
        )
        self.status_label.grid(row=3, column=0, pady=(0, 12))

        self.toggle_button = customtkinter.CTkButton(
            self, text="Start daemon", width=180, height=42, command=self._toggle
        )
        self.toggle_button.grid(row=4, column=0, pady=(0, 12))
        self._btn_fg = self.toggle_button.cget("fg_color")
        self._btn_hover = self.toggle_button.cget("hover_color")

        self.explanation_label = customtkinter.CTkLabel(
            self,
            text="Click Start to watch your screen. When the app detects a "
            "scoreboard it takes a screenshot and saves it to the Screenshots "
            "tab.",
            wraplength=560,
            justify="center",
            text_color=("gray25", "gray75"),
        )
        self.explanation_label.grid(row=5, column=0, pady=(0, 20))

        self._load_logo()

    def _load_logo(self):
        path = runtime_paths.assets_dir() / "chat_welcome.png"
        try:
            img = Image.open(path)
        except OSError:
            return
        w, h = fit_size(img.width, img.height, LOGO_BOX[0], LOGO_BOX[1])
        self.logo_label.configure(
            image=customtkinter.CTkImage(
                light_image=img, dark_image=img, size=(w, h)
            )
        )

    # ------------------------------------------------------------------
    # Status / actions
    # ------------------------------------------------------------------

    def _toggle(self):
        if daemon_running():
            self._stop()
        else:
            self._start()

    def refresh(self):
        self._refresh_status()

    def _start(self):
        cmd = build_daemon_command()
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs
            )
        except OSError as exc:
            self.status_label.configure(
                text=f"✗ Could not start: {exc}", text_color="#ff6b6b"
            )
            return
        self._refresh_status()

    def _stop(self):
        code = daemon.stop_daemon()
        if code != 0:
            self.status_label.configure(
                text="✗ Could not stop daemon", text_color="#ff6b6b"
            )
        self._refresh_status()

    def _refresh_status(self):
        running = daemon_running()
        if running:
            self.status_label.configure(
                text="● Running — watching your screen",
                text_color=RUNNING_COLOR,
            )
            self.toggle_button.configure(
                text="Stop daemon", fg_color="#a52a2a", hover_color="#8b1a1a"
            )
        else:
            self.status_label.configure(text="● Stopped", text_color=STOPPED_COLOR)
            self.toggle_button.configure(
                text="Start daemon",
                fg_color=self._btn_fg,
                hover_color=self._btn_hover,
            )

    def _poll(self):
        self._refresh_status()
        self.after(POLL_MS, self._poll)
