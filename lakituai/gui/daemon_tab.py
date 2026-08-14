"""Auto Capture tab for the LakituAI GUI.

Lets the user turn the background screen watcher on and off straight from the
app and shows whether it is currently active. Starting spawns the watcher as a
separate process (``--daemon``); stopping uses the pid file the same way
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
    """Command that launches the background watcher (source or frozen exe)."""

    if runtime_paths.is_frozen():
        return [sys.executable, "--daemon"]
    return [sys.executable, "-m", "lakituai", "--daemon"]


def daemon_running() -> bool:
    """True when a live watcher process owns the pid file."""

    pid_path = daemon.DEFAULT_PID_PATH
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False
    return daemon._process_alive(pid)


class DaemonTab(customtkinter.CTkFrame):
    """On/off switch for the background watcher plus a status indicator."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._starting = False
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
        self.status_label.grid(row=3, column=0, pady=(6, 10))

        self.switch = customtkinter.CTkSwitch(
            self,
            text="App active",
            font=customtkinter.CTkFont(size=16),
            command=self._on_switch,
        )
        self.switch.grid(row=4, column=0, pady=(0, 12))

        self.explanation_label = customtkinter.CTkLabel(
            self,
            text="Turn the app on to watch your screen. When a race "
            "scoreboard appears, the app saves a screenshot to the "
            "Screenshots tab.",
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
            image=customtkinter.CTkImage(light_image=img, dark_image=img, size=(w, h))
        )

    # ------------------------------------------------------------------
    # Status / actions
    # ------------------------------------------------------------------

    def refresh(self):
        self._refresh_status()

    def _on_switch(self):
        if self.switch.get():
            self._start()
        else:
            self._stop()

    def _start(self):
        if daemon_running() or self._starting:
            return
        cmd = build_daemon_command()
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs
            )
            self._starting = True
        except OSError as exc:
            self.status_label.configure(
                text=f"✗ Could not start: {exc}", text_color="#ff6b6b"
            )
            self.switch.deselect()
        self._refresh_status()

    def _stop(self):
        if not daemon_running():
            return
        code = daemon.stop_daemon()
        if code != 0:
            self.status_label.configure(
                text="✗ Could not stop", text_color="#ff6b6b"
            )
        self._refresh_status()

    def _refresh_status(self):
        running = daemon_running()
        if running:
            self._starting = False
            self.switch.select()
            self.status_label.configure(
                text="● Active — watching your screen", text_color=RUNNING_COLOR
            )
        else:
            self.switch.deselect()
            self.status_label.configure(text="● Stopped", text_color=STOPPED_COLOR)

    def _poll(self):
        self._refresh_status()
        self.after(POLL_MS, self._poll)
