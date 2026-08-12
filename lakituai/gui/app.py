"""Desktop GUI for LakituAI (CustomTkinter).

Run with: python -m lakituai --gui

The main window uses a collapsible sidebar navigation (hamburger style):
- Collapsed: only the tab icons are shown, stacked vertically.
- Clicking an icon switches to that tab.
- Clicking the hamburger button ("☰") expands the sidebar and reveals
  the tab names next to their icons.

Tab icons are loaded from PNG files in assets/. If a tab has no image
yet, a Unicode symbol is used as fallback (chosen from DejaVu Sans so
they render reliably on Linux).
"""

import customtkinter
from PIL import Image

from lakituai.gui.chat_tab import ChatTab
from lakituai.gui.players_tab import PlayersTab
from lakituai.gui.race_summary_tab import RaceSummaryTab
from lakituai.gui.wars_tab import WarsTab
from lakituai.runtime_paths import assets_dir

ASSETS_DIR = assets_dir()

# Icon and button sizing (shared by NavButton and App).
ICON_IMAGE_SIZE = 36
BUTTON_HEIGHT = 54


class NavButton(customtkinter.CTkFrame):
    """Clickable sidebar item: icon + smaller text label.

    A frame instead of a CTkButton because icon and text need different
    font sizes; a single CTkButton font clips long names like
    'Race Summary' when rendered at icon size.

    The icon can be either an image (PIL Image) or a Unicode symbol.
    """

    def __init__(
        self,
        master,
        icon: str,
        text: str,
        command,
        icon_font_size: int = 20,
        image: Image.Image = None,
    ):
        super().__init__(
            master,
            height=BUTTON_HEIGHT,
            corner_radius=8,
            fg_color="transparent",
            cursor="hand2",
        )
        # Fixed height so the button does not grow with its labels.
        self.pack_propagate(False)

        self._command = command
        self._active = False

        if image is not None:
            ctk_image = customtkinter.CTkImage(
                light_image=image, dark_image=image, size=(ICON_IMAGE_SIZE, ICON_IMAGE_SIZE)
            )
            self.icon_label = customtkinter.CTkLabel(
                self, image=ctk_image, text="", cursor="hand2"
            )
        else:
            self.icon_label = customtkinter.CTkLabel(
                self,
                text=icon,
                font=customtkinter.CTkFont(size=icon_font_size),
                cursor="hand2",
            )
        self.icon_label.pack(side="left", padx=(8, 0))

        self.text_label = customtkinter.CTkLabel(
            self,
            text=text,
            font=customtkinter.CTkFont(size=13),
            anchor="w",
            cursor="hand2",
        )
        self.text_label.pack(side="left", padx=(8, 8), fill="x", expand=True)

        # Clicks and hover work on the frame and both labels.
        for widget in (self, self.icon_label, self.text_label):
            widget.bind("<Button-1>", lambda event: self._on_click())
            widget.bind("<Enter>", lambda event: self._on_enter())
            widget.bind("<Leave>", lambda event: self._on_leave())

    def _on_click(self):
        if self._command:
            self._command()

    def _on_enter(self):
        if not self._active:
            self.configure(fg_color=("gray80", "gray20"))

    def _on_leave(self):
        if not self._active:
            self.configure(fg_color="transparent")

    def set_active(self, active: bool):
        """Highlight the button when it is the selected tab."""
        self._active = active
        self.configure(fg_color=("gray75", "gray25") if active else "transparent")

    def show_text(self, show: bool):
        """Show or hide the tab name (collapsed sidebar hides it)."""
        if show:
            self.text_label.pack(side="left", padx=(8, 8), fill="x", expand=True)
        else:
            self.text_label.pack_forget()


class App(customtkinter.CTk):
    # (tab name, icon). Icons must exist in DejaVu Sans (U+2600-U+2BFF).
    TABS = [
        ("Chat", "✉"),           # envelope
        ("Race Summary", "⚑"),   # flag
        ("Wars", "⚔"),           # crossed swords
        ("Players", "☻"),        # smiling face
    ]
    ICON_FONT_SIZE = 26
    SIDEBAR_COLLAPSED = 70
    SIDEBAR_EXPANDED = 200

    def __init__(self):
        super().__init__()

        self.title("LakituAI")
        self.geometry("1100x700")
        self.minsize(700, 480)
        self._set_window_icon()

        self._sidebar_expanded = True
        self._current_tab = 0

        self.pages = {}
        self.tab_buttons = {}

        self._build_main_layout()
        self._build_sidebar()
        self._build_pages()

        self._select_tab(0)

    def _set_window_icon(self):
        """Set the app logo as the window icon (title bar + taskbar)."""
        logo_path = ASSETS_DIR / "logo.png"
        if not logo_path.exists():
            return
        try:
            from PIL import Image, ImageTk

            size = 128
            img = Image.open(logo_path).resize((size, size))
            self._icon_image = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._icon_image)
        except Exception:
            pass

    def _build_main_layout(self):
        """Split the window into a sidebar (left) and a content area."""
        self.main_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True)

        # Sidebar keeps a fixed width; pack_propagate(False) prevents the
        # widgets inside from forcing a different size.
        self.sidebar = customtkinter.CTkFrame(
            self.main_frame, width=self.SIDEBAR_EXPANDED, corner_radius=0
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Content area holds one page per tab; only one is visible at a time.
        self.content = customtkinter.CTkFrame(self.main_frame, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)

    def _build_sidebar(self):
        """Hamburger button + one vertical button per tab."""
        self.menu_button = customtkinter.CTkButton(
            self.sidebar,
            text="☰",
            width=44,
            height=44,
            font=("", 22),
            fg_color="transparent",
            command=self._toggle_sidebar,
        )
        # anchor="w" keeps the hamburger pinned to the left edge even when
        # the sidebar expands.
        self.menu_button.pack(padx=10, pady=(10, 20), anchor="w")

        for i, (name, icon) in enumerate(self.TABS):
            btn = NavButton(
                self.sidebar,
                icon=icon,
                text=name,
                command=lambda i=i: self._select_tab(i),
                icon_font_size=self.ICON_FONT_SIZE,
                image=self._load_tab_image(name),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.tab_buttons[name] = btn

    def _load_tab_image(self, name: str):
        """Load the PNG icon for a tab, or None if the tab has no asset.

        Asset names follow the tab name lowercased with spaces -> '_'
        (e.g., 'Race Summary' -> 'race_summary.png').
        """
        filename = name.lower().replace(" ", "_") + ".png"
        path = ASSETS_DIR / filename
        if not path.exists():
            return None
        try:
            return Image.open(path)
        except Exception:
            return None

    def _build_pages(self):
        """Create one page frame per tab and build their contents."""
        for name, _ in self.TABS:
            self.pages[name] = customtkinter.CTkFrame(self.content, corner_radius=0)

        self.chat_session = None
        try:
            from lakituai.chat.agents import ChatSession

            self.chat_session = ChatSession()
        except ImportError:
            self.chat_session = None

        # Each tab lives in its own module; build them here in order.
        ChatTab(self.pages["Chat"], self.chat_session).pack(fill="both", expand=True)
        RaceSummaryTab(self.pages["Race Summary"]).pack(fill="both", expand=True)
        WarsTab(self.pages["Wars"]).pack(fill="both", expand=True)
        PlayersTab(self.pages["Players"]).pack(fill="both", expand=True)

    def _toggle_sidebar(self):
        """Expand or collapse the sidebar, showing/hiding tab names."""
        self._sidebar_expanded = not self._sidebar_expanded
        width = self.SIDEBAR_EXPANDED if self._sidebar_expanded else self.SIDEBAR_COLLAPSED
        self.sidebar.configure(width=width)

        for _, name in self.tab_buttons.items():
            name.show_text(self._sidebar_expanded)

    def _select_tab(self, index):
        """Show the selected page and highlight its sidebar button."""
        self._current_tab = index
        name = self.TABS[index][0]

        for page_name, page in self.pages.items():
            if page_name == name:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()

        self._style_tab_buttons()

    def _style_tab_buttons(self):
        """Highlight the active tab button."""
        for i, (name, _) in enumerate(self.TABS):
            self.tab_buttons[name].set_active(i == self._current_tab)


def run_gui() -> None:
    """Launch the LakituAI desktop GUI."""

    customtkinter.set_appearance_mode("dark")
    customtkinter.set_default_color_theme("blue")

    app = App()

    app.mainloop()
