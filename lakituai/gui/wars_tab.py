"""Wars tab for the LakituAI GUI.

Shows, for the selected war:
- its info (name, creation date, races played, teams),
- the final standings (teams and players), i.e. through the most recent race,
- a war list on the right where each war can be deleted (X button).

The war list defaults to the current war (current_war.json).
"""

import datetime

import customtkinter

from lakituai import persistence, war_manager
from lakituai.gui.players_tab import ConfirmDialog


class WarsTab(customtkinter.CTkFrame):
    """War info + final standings + war list (with delete) for all wars."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        persistence.init_db()

        self.wars = []
        self.current_war_id = None
        self.current_war_name = None
        self.war_buttons = {}
        self.delete_buttons = {}
        self.current_buttons = {}

        self._build()
        self.refresh()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # Left: info (war info on top, standings below), each scrollable
        info = customtkinter.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=(10, 10))
        info.grid_columnconfigure(0, weight=1)
        info.grid_rowconfigure(1, weight=1)

        self.detail_panel = customtkinter.CTkFrame(info, fg_color="transparent")
        self.detail_panel.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        self.standings_panel = self._make_scrollable_panel(info)
        self.standings_panel["wrapper"].grid(row=1, column=0, sticky="nsew")

        # Right: war list (always visible)
        self.war_panel = customtkinter.CTkFrame(self, width=280, fg_color="transparent")
        self.war_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=(10, 10))
        self.war_panel.grid_columnconfigure(0, weight=1)
        self.war_panel.grid_rowconfigure(2, weight=1)

        # Header: title + reload
        header = customtkinter.CTkFrame(self.war_panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))
        header.grid_columnconfigure(0, weight=1)

        customtkinter.CTkLabel(
            header, text="WARS", font=customtkinter.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        self.reload_button = customtkinter.CTkButton(
            header, text="⟳", width=30, height=26, command=self.refresh
        )
        self.reload_button.grid(row=0, column=1, sticky="e")

        # Create-war box
        create_box = customtkinter.CTkFrame(
            self.war_panel, corner_radius=8, fg_color=("gray78", "gray20")
        )
        create_box.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        create_box.grid_columnconfigure(0, weight=1)

        self.new_war_entry = customtkinter.CTkEntry(
            create_box, placeholder_text="New war name"
        )
        self.new_war_entry.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)
        self.new_war_entry.bind("<Return>", lambda e: self._create_war())

        self.create_button = customtkinter.CTkButton(
            create_box, text="Create", width=64, height=28, command=self._create_war
        )
        self.create_button.grid(row=0, column=1, padx=(4, 8), pady=6)

        self.war_list = customtkinter.CTkScrollableFrame(
            self.war_panel, fg_color="transparent"
        )
        self.war_list.grid(row=2, column=0, sticky="nsew", padx=4)
        self.war_list.grid_columnconfigure(0, weight=1)

    @staticmethod
    def _make_scrollable_panel(parent):
        """Scrollable frame kept at its grid cell size (does not grow with content)."""
        wrapper = customtkinter.CTkFrame(parent, fg_color="transparent")
        wrapper.grid_propagate(False)
        scroll = customtkinter.CTkScrollableFrame(wrapper, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        return {"wrapper": wrapper, "scroll": scroll}

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload wars and re-render everything."""
        self.wars = persistence.list_wars()
        self.current_war_name = war_manager.load_current_war()

        if not self.wars:
            self.current_war_id = None
            self._clear_children(self.detail_panel)
            self._clear_children(self.standings_panel["scroll"])
            self._add_message(self.detail_panel, "No wars found yet.")
            self._populate_wars()
            return

        self._populate_wars()

        current = self.current_war_name
        target = next(
            (w for w in self.wars if w["name"] == current),
            self.wars[0],
        )
        self._select_war(target["war_id"])

    def _populate_wars(self):
        for widget in self.war_list.winfo_children():
            widget.destroy()
        self.war_buttons = {}
        self.delete_buttons = {}
        self.current_buttons = {}

        for war in self.wars:
            label = war["name"]
            if war["races_count"]:
                races = "1 race" if war["races_count"] == 1 else f"{war['races_count']} races"
                label += f"  ({races})"

            row = customtkinter.CTkFrame(self.war_list, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)

            war_id = war["war_id"]
            is_current = war["name"] == self.current_war_name

            cur_btn = customtkinter.CTkButton(
                row,
                text="●" if is_current else "○",
                width=26,
                height=32,
                fg_color="transparent",
                hover_color=("gray75", "gray30"),
                text_color=("#b8860b", "#ffd700") if is_current else ("gray40", "gray70"),
                command=lambda wid=war_id: self._set_current_war(wid),
            )
            cur_btn.grid(row=0, column=0, padx=(0, 2))

            btn = customtkinter.CTkButton(
                row,
                text=label,
                anchor="w",
                height=32,
                fg_color="transparent",
                command=lambda wid=war_id: self._select_war(wid),
            )
            btn.grid(row=0, column=1, sticky="ew")

            delete_btn = customtkinter.CTkButton(
                row,
                text="✕",
                width=28,
                height=32,
                fg_color="transparent",
                hover_color="#a52a2a",
                text_color=("gray40", "gray70"),
                command=lambda wid=war_id: self._confirm_delete_war(wid),
            )
            delete_btn.grid(row=0, column=2, padx=(4, 0))

            self.war_buttons[war_id] = btn
            self.delete_buttons[war_id] = delete_btn
            self.current_buttons[war_id] = cur_btn

    def _create_war(self):
        """Create a new war (or reuse an existing name) and make it current."""
        name = self.new_war_entry.get().strip()
        if not name:
            return
        war_id = persistence.get_or_create_war(name)
        self.new_war_entry.delete(0, "end")
        war_manager.set_current_war(name)
        self.refresh()
        self._select_war(war_id)

    def _set_current_war(self, war_id):
        """Set the given war as the current war."""
        war = self._fetch_war_detail(war_id)
        if war is None:
            return
        war_manager.set_current_war(war["name"])
        self.refresh()
        self._select_war(war_id)

    def _select_war(self, war_id):
        self.current_war_id = war_id
        for wid, btn in self.war_buttons.items():
            btn.configure(fg_color=("gray75", "gray25") if wid == war_id else "transparent")
        self._render_detail()
        self._render_standings()

    def _fetch_war_detail(self, war_id):
        return next((w for w in self.wars if w["war_id"] == war_id), None)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_detail(self):
        panel = self.detail_panel
        self._clear_children(panel)
        war = self._fetch_war_detail(self.current_war_id)
        if war is None:
            self._add_message(panel, "War not found.")
            return

        # Title box
        title_box = customtkinter.CTkFrame(
            panel, corner_radius=8, fg_color=("gray80", "gray22")
        )
        title_box.pack(fill="x", padx=6, pady=4)
        customtkinter.CTkLabel(
            title_box,
            text=war["name"],
            font=customtkinter.CTkFont(size=22, weight="bold"),
        ).pack(pady=8)

        self._add_section_title(panel, "INFO")

        info_table = customtkinter.CTkFrame(panel, corner_radius=6, fg_color="transparent")
        info_table.pack(fill="x", padx=10, pady=(0, 6))
        info_table.grid_columnconfigure(1, weight=1)

        created = self._format_created_at(war["created_at"])
        info_rows = [
            ("Created", created),
            ("Races", str(war["races_count"])),
            ("Teams", ", ".join(war["teams"]) if war["teams"] else "(none)"),
        ]
        for i, (key, value) in enumerate(info_rows):
            customtkinter.CTkLabel(
                info_table, text=key, anchor="w", text_color=("gray40", "gray70"),
                font=customtkinter.CTkFont(size=12, weight="bold"),
            ).grid(row=i, column=0, padx=8, pady=2, sticky="w")
            customtkinter.CTkLabel(
                info_table, text=value, anchor="w"
            ).grid(row=i, column=1, padx=8, pady=2, sticky="w")

    def _render_standings(self):
        panel = self.standings_panel["scroll"]
        self._clear_children(panel)
        if self.current_war_id is None:
            self._add_message(panel, "Select a war to see standings.")
            return

        teams = persistence.get_team_standings(self.current_war_id)
        players = persistence.get_player_standings(self.current_war_id)

        title_box = customtkinter.CTkFrame(
            panel, corner_radius=8, fg_color=("gray80", "gray22")
        )
        title_box.pack(fill="x", padx=6, pady=4)
        customtkinter.CTkLabel(
            title_box,
            text="FINAL STANDINGS",
            font=customtkinter.CTkFont(size=18, weight="bold"),
        ).pack(pady=6)

        if teams:
            self._add_section_title(panel, "TEAMS")
            self._build_standings_table(panel, teams.items())
        if players:
            self._add_section_title(panel, "PLAYERS")
            self._build_standings_table(panel, players.items())
        if not teams and not players:
            self._add_message(panel, "(no data yet)")

    @staticmethod
    def _format_created_at(created_at):
        if not created_at:
            return "(unknown)"
        try:
            dt = datetime.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return created_at
        return dt.strftime("%b %d, %Y")

    # ------------------------------------------------------------------
    # Table builders
    # ------------------------------------------------------------------

    @staticmethod
    def _add_section_title(parent, text):
        customtkinter.CTkLabel(
            parent,
            text=text,
            font=customtkinter.CTkFont(size=13, weight="bold"),
            text_color=("gray40", "gray70"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(6, 2))

    def _build_standings_table(self, parent, entries):
        table = customtkinter.CTkFrame(parent, corner_radius=6, fg_color="transparent")
        table.pack(fill="x", padx=10, pady=(0, 6))
        table.grid_columnconfigure(0, weight=0, minsize=40)
        table.grid_columnconfigure(1, weight=1)
        table.grid_columnconfigure(2, weight=0, minsize=50)

        for col, text in enumerate(("POS", "NAME", "PTS")):
            customtkinter.CTkLabel(
                table,
                text=text,
                font=customtkinter.CTkFont(size=12, weight="bold"),
                text_color=("gray40", "gray70"),
                anchor="w",
            ).grid(row=0, column=col, padx=8, pady=(2, 2), sticky="w")

        for i, (name, pts) in enumerate(entries, start=1):
            customtkinter.CTkLabel(
                table, text=str(i), anchor="w", text_color="gray"
            ).grid(row=i, column=0, padx=8, pady=2, sticky="w")
            customtkinter.CTkLabel(table, text=name, anchor="w").grid(
                row=i, column=1, padx=8, pady=2, sticky="w"
            )
            customtkinter.CTkLabel(table, text=str(pts), anchor="e").grid(
                row=i, column=2, padx=8, pady=2, sticky="e"
            )

    # ------------------------------------------------------------------
    # War deletion
    # ------------------------------------------------------------------

    def _confirm_delete_war(self, war_id):
        war = self._fetch_war_detail(war_id)
        name = war["name"] if war else f"war #{war_id}"
        ConfirmDialog(
            self,
            title="Delete war",
            message=f"Delete '{name}'?\nAll its races, results and standings "
                    "will be removed.",
            on_confirm=lambda: self._delete_war(war_id),
        )

    def _delete_war(self, war_id):
        persistence.delete_war(war_id)
        self.refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clear_children(frame):
        for widget in frame.winfo_children():
            widget.destroy()

    @staticmethod
    def _add_message(parent, text):
        customtkinter.CTkLabel(
            parent, text=text, text_color="gray", justify="left", anchor="w"
        ).pack(fill="x", padx=10, pady=6)
