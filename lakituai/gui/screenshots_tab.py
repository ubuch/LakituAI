"""Screenshots tab for the LakituAI GUI.

Shows the screenshots captured by the background daemon: a large viewer in
the center (aspect-ratio preserved) with an identifying caption below, a
scrollable thumbnail rail on the right, and a reload button so new captures
appear without restarting the app. The folder is also polled in the
background and the view auto-refreshes whenever a capture lands.
"""

import re
from datetime import datetime
from pathlib import Path

import customtkinter
from PIL import Image

from lakituai import logic
from lakituai.gui.players_tab import ConfirmDialog

THUMB_HEIGHT = 84
THUMB_COL_WIDTH = 210
AUTO_REFRESH_MS = 3000
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def list_screenshots(screenshots_dir=None) -> list[Path]:
    """Return screenshot paths in the folder, newest first (empty when none)."""

    directory = Path(screenshots_dir or logic.SCREENSHOTS_DIR)
    if not directory.is_dir():
        return []
    items = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return items


def parse_caption(path) -> str:
    """Human-readable label for a daemon screenshot name.

    Daemon screenshots are named ``auto_N.jpg`` (or the legacy
    ``auto_YYYYMMDD_HHMMSSffffff.jpg``). The numbered form has no timestamp in
    the name, so the file modification time is used. Falls back to the file
    modification time for any other name.
    """

    stem = Path(path).stem
    m = re.match(r"auto_(\d{8})_(\d{6})", stem)
    if m:
        try:
            stamp = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            return stamp.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    try:
        mtime = datetime.fromtimestamp(Path(path).stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except OSError:
        mtime = ""
    m = re.match(r"auto_(\d+)", stem)
    if m:
        label = f"Screenshot {m.group(1)}"
        return f"{label} - {mtime}" if mtime else label
    return mtime


def fit_size(img_w: int, img_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    """Largest (w, h) that fits inside box_w x box_h, preserving aspect ratio.

    Never upscales: images smaller than the box are shown at native size.
    """

    if img_w <= 0 or img_h <= 0 or box_w <= 0 or box_h <= 0:
        return max(1, img_w), max(1, img_h)
    scale = min(box_w / img_w, box_h / img_h, 1.0)
    return max(1, int(img_w * scale)), max(1, int(img_h * scale))


class ScreenshotsTab(customtkinter.CTkFrame):
    """Viewer + thumbnail rail for the daemon's captured screenshots."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._items: list[Path] = []
        self._current: Path | None = None
        self._pil: Image.Image | None = None
        self._last_viewer_size: tuple[int, int] | None = None
        self._rows: list[customtkinter.CTkFrame] = []
        self._empty_label: customtkinter.CTkLabel | None = None
        self._last_snapshot: list[tuple[str, int]] | None = None
        self._build()
        self.refresh()
        self._last_snapshot = self._folder_snapshot()
        self._poll()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, minsize=THUMB_COL_WIDTH, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # Top bar: title + reload button.
        top = customtkinter.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        top.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(top, text="Screenshots", anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.reload_button = customtkinter.CTkButton(
            top, text="⟳", width=36, command=self.refresh
        )
        self.reload_button.grid(row=0, column=1, padx=(6, 0))

        # Center: big image + caption.
        self.viewer = customtkinter.CTkFrame(self, corner_radius=8)
        self.viewer.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(10, 8))
        self.viewer.grid_rowconfigure(0, weight=1)
        self.viewer.grid_columnconfigure(0, weight=1)

        self.image_label = customtkinter.CTkLabel(
            self.viewer, text="", fg_color="transparent"
        )
        self.image_label.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.caption_label = customtkinter.CTkLabel(
            self.viewer,
            text="",
            anchor="center",
            text_color=("gray25", "gray75"),
            justify="center",
        )
        self.caption_label.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

        self.viewer.bind("<Configure>", self._on_viewer_resize)

        # Right: vertical thumbnail rail.
        self.rail = customtkinter.CTkScrollableFrame(self, width=THUMB_COL_WIDTH)
        self.rail.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(10, 8))

    def _folder_snapshot(self) -> list[tuple[str, int]]:
        """(name, mtime_ns) pairs used to detect new/deleted screenshots."""
        return [(p.name, p.stat().st_mtime_ns) for p in list_screenshots()]

    def _poll(self):
        """Auto-refresh the rail whenever the screenshots folder changes."""
        if not self.winfo_exists():
            return
        snapshot = self._folder_snapshot()
        if snapshot != self._last_snapshot:
            self._last_snapshot = snapshot
            self.refresh()
        self.after(AUTO_REFRESH_MS, self._poll)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload the folder and re-render the rail and viewer."""
        self._items = list_screenshots()
        if self._current is None or self._current not in self._items:
            self._select(self._items[0] if self._items else None)
        else:
            self._render_viewer()
        self._render_rail()

    def _render_rail(self):
        for row in self._rows:
            row.destroy()
        self._rows = []
        if self._empty_label is not None:
            self._empty_label.destroy()
            self._empty_label = None

        if not self._items:
            self._empty_label = customtkinter.CTkLabel(
                self.rail, text="No screenshots yet.", text_color="gray"
            )
            self._empty_label.pack(padx=6, pady=10)
            return

        for path in self._items:
            row = customtkinter.CTkFrame(self.rail, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)

            try:
                img = Image.open(path)
                w, h = fit_size(
                    img.width, img.height, THUMB_COL_WIDTH - 46, THUMB_HEIGHT
                )
                thumb = customtkinter.CTkImage(
                    light_image=img, dark_image=img, size=(w, h)
                )
            except OSError:
                thumb = None

            if thumb is not None:
                thumb_label = customtkinter.CTkLabel(
                    row, image=thumb, text="", cursor="hand2"
                )
            else:
                thumb_label = customtkinter.CTkLabel(
                    row, text="(unreadable)", text_color="gray", cursor="hand2"
                )
            thumb_label.grid(row=0, column=0, padx=(4, 0), pady=4, sticky="w")
            thumb_label.bind("<Button-1>", lambda e, p=path: self._select(p))
            row.bind("<Button-1>", lambda e, p=path: self._select(p))

            del_btn = customtkinter.CTkButton(
                row,
                text="✕",
                width=30,
                height=THUMB_HEIGHT - 16,
                fg_color="#a52a2a",
                hover_color="#8b1a1a",
                command=lambda p=path: self._delete(p),
            )
            del_btn.grid(row=0, column=1, padx=(0, 4), pady=4)

            self._rows.append(row)

        self._highlight_selected()

    def _select(self, path: Path | None):
        self._current = path
        if path is None:
            self._pil = None
            self._last_viewer_size = None
            self.image_label.configure(image=None, text="No screenshots yet.")
            self.caption_label.configure(text="")
            self._highlight_selected()
            return
        try:
            self._pil = Image.open(path)
        except OSError:
            self._pil = None
            self.image_label.configure(image=None, text="(unreadable)")
            self.caption_label.configure(text=path.name)
            return
        self._render_viewer()
        self._highlight_selected()

    def _render_viewer(self):
        if self._pil is None:
            return
        self.image_label.configure(
            image=customtkinter.CTkImage(
                light_image=self._pil,
                dark_image=self._pil,
                size=fit_size(
                    self._pil.width,
                    self._pil.height,
                    self.viewer.winfo_width(),
                    self.viewer.winfo_height(),
                ),
            ),
            text="",
        )
        self._last_viewer_size = (
            self.viewer.winfo_width(),
            self.viewer.winfo_height(),
        )
        self.caption_label.configure(
            text=f"{self._current.name}\n{parse_caption(self._current)}"
        )

    def _on_viewer_resize(self, event):
        if self._pil is None:
            return
        if (event.width, event.height) == self._last_viewer_size:
            return
        self._last_viewer_size = (event.width, event.height)
        self.image_label.configure(
            image=customtkinter.CTkImage(
                light_image=self._pil,
                dark_image=self._pil,
                size=fit_size(self._pil.width, self._pil.height, event.width, event.height),
            ),
            text="",
        )

    def _highlight_selected(self):
        for row in self._rows:
            row.configure(fg_color=("gray80", "gray22"))
        if self._current is None:
            return
        for i, path in enumerate(self._items):
            if path == self._current and i < len(self._rows):
                self._rows[i].configure(fg_color=("gray65", "gray35"))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _delete(self, path: Path):
        ConfirmDialog(
            self,
            title="Delete screenshot",
            message=f"Delete this screenshot?\n{Path(path).name}",
            on_confirm=lambda: self._delete_now(path),
        )

    def _delete_now(self, path: Path):
        try:
            Path(path).unlink()
        except OSError:
            pass
        self.refresh()
