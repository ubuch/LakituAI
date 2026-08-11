"""Race Summary tab for the LakituAI GUI.

Shows, for the selected war:
- the detail of the selected race (team result with net points + scoreboard)
  with standings that evolve per race (cumulative through the selected race),
- a race list on the right where each race can be deleted (X button).

The war selector defaults to the current war (current_war.json).
"""

import json
from pathlib import Path

import customtkinter

from lakituai import persistence, war_manager
from lakituai.gui.players_tab import ConfirmDialog


class RaceSummaryTab(customtkinter.CTkFrame):
    """Race detail + per-race standings + race list (with delete) for a war."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        persistence.init_db()

        self.wars = []
        self.current_war_id = None
        self.race_buttons = {}
        self.delete_buttons = {}
        self.selected_race = None

        self._build()
        self.refresh()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # Top bar: war selector + refresh
        top = customtkinter.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 5))
        top.grid_columnconfigure(1, weight=1)

        customtkinter.CTkLabel(top, text="War:").grid(row=0, column=0, padx=(0, 5))
        self.war_menu = customtkinter.CTkOptionMenu(
            top, values=["..."], width=280, command=self._on_war_change
        )
        self.war_menu.grid(row=0, column=1, padx=5, sticky="w")

        self.refresh_button = customtkinter.CTkButton(
            top, text="⟳", width=40, command=self.refresh
        )
        self.refresh_button.grid(row=0, column=2, padx=5)

        # Left: info (detail on top, standings below), each scrollable
        info = customtkinter.CTkFrame(self, fg_color="transparent")
        info.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        info.grid_columnconfigure(0, weight=1)
        info.grid_rowconfigure(0, weight=3)
        info.grid_rowconfigure(1, weight=2)

        self.detail_panel = self._make_scrollable_panel(info)
        self.detail_panel["wrapper"].grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        self.standings_panel = self._make_scrollable_panel(info)
        self.standings_panel["wrapper"].grid(row=1, column=0, sticky="nsew")

        # Right: race list (always visible)
        self.race_panel = customtkinter.CTkFrame(self, width=250, fg_color="transparent")
        self.race_panel.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        self.race_panel.grid_columnconfigure(0, weight=1)
        self.race_panel.grid_rowconfigure(1, weight=1)

        customtkinter.CTkLabel(
            self.race_panel, text="RACES", font=customtkinter.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(0, 4))

        self.race_list = customtkinter.CTkScrollableFrame(
            self.race_panel, fg_color="transparent"
        )
        self.race_list.grid(row=1, column=0, sticky="nsew", padx=4)
        self.race_list.grid_columnconfigure(0, weight=1)

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
        names = [w["name"] for w in self.wars]

        if not names:
            self.war_menu.configure(values=["(no wars)"])
            self.war_menu.set("(no wars)")
            self.war_menu.configure(state="disabled")
            self.current_war_id = None
            self._clear_children(self.detail_panel["scroll"])
            self._clear_children(self.standings_panel["scroll"])
            self._add_message(self.detail_panel["scroll"], "No wars found yet.")
            return

        self.war_menu.configure(state="normal", values=names)

        current = war_manager.load_current_war()
        if current in names:
            self.war_menu.set(current)
        else:
            self.war_menu.set(names[0])

        self._on_war_change(self.war_menu.get())

    def _on_war_change(self, name):
        war = next((w for w in self.wars if w["name"] == name), None)
        if war is None:
            return
        self.current_war_id = war["war_id"]

        races = self._fetch_races(self.current_war_id)
        self._populate_races(races)
        if races:
            self._select_race(races[0]["race_number"])
        else:
            self._clear_children(self.detail_panel["scroll"])
            self._clear_children(self.standings_panel["scroll"])
            self._add_message(
                self.detail_panel["scroll"],
                "No races saved for this war yet.\n\n"
                "Process a screenshot from the CLI to add races.",
            )
            self._add_message(self.standings_panel["scroll"], "(no standings yet)")

    def _fetch_races(self, war_id):
        conn = persistence.sqlite3.connect(str(persistence.DB_PATH))
        conn.row_factory = persistence.sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.race_number,
                   tr.team_tag, tr.net_points
            FROM races r
            LEFT JOIN team_race_results tr ON tr.race_id = r.id
            WHERE r.war_id = ?
            ORDER BY r.race_number, tr.net_points DESC
            """,
            (war_id,),
        )
        rows = cursor.fetchall()
        conn.close()

        races = {}
        for row in rows:
            rn = row["race_number"]
            races.setdefault(rn, {"race_number": rn, "teams": []})
            if row["team_tag"]:
                races[rn]["teams"].append((row["team_tag"], row["net_points"]))

        result = []
        for rn in sorted(races):
            result.append(
                {
                    "race_number": rn,
                    "label": self._race_label(races[rn]["teams"]),
                }
            )
        return result

    @staticmethod
    def _race_label(teams):
        """Short race result for the list: winning team + net, or 'Tie'."""
        if not teams:
            return ""
        best_tag, best_net = max(teams, key=lambda team: team[1])
        if best_net > 0:
            return f"{best_tag} +{best_net}"
        return "Tie"

    def _fetch_race_detail(self, war_id, race_number):
        conn = persistence.sqlite3.connect(str(persistence.DB_PATH))
        conn.row_factory = persistence.sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, json_path FROM races WHERE war_id = ? AND race_number = ?",
            (war_id, race_number),
        )
        race = cursor.fetchone()
        if not race:
            conn.close()
            return None

        cursor.execute(
            """
            SELECT player_name, position, points
            FROM race_results
            WHERE race_id = ?
            ORDER BY position
            """,
            (race["id"],),
        )
        results = cursor.fetchall()

        cursor.execute(
            """
            SELECT team_tag, points, net_points
            FROM team_race_results
            WHERE race_id = ?
            ORDER BY points DESC
            """,
            (race["id"],),
        )
        teams = cursor.fetchall()
        conn.close()

        # Races saved before the team_race_results feature have no stored
        # team result; recompute it from the scoreboard using team tags.
        if not teams:
            teams = self._compute_team_result(results)

        bot_positions = self._load_bot_positions(race["json_path"])
        return {
            "teams": [
                {
                    "team_tag": team["team_tag"],
                    "points": team["points"],
                    "net_points": team["net_points"],
                }
                for team in teams
            ],
            "results": [
                {
                    "position": row["position"],
                    "player_name": row["player_name"],
                    "points": row["points"],
                    "is_bot": row["position"] in bot_positions,
                }
                for row in results
            ],
        }

    @staticmethod
    def _load_bot_positions(json_path):
        """Row numbers whose OCR text was a bot (from the race JSON)."""
        if not json_path:
            return set()
        try:
            with open(Path(json_path), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return set()
        return {
            row["row_number"]
            for row in data.get("rows", [])
            if row.get("is_bot")
        }

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_detail(self, race_number):
        panel = self.detail_panel["scroll"]
        self._clear_children(panel)
        detail = self._fetch_race_detail(self.current_war_id, race_number)
        if detail is None:
            self._add_message(panel, f"Race #{race_number} not found.")
            return

        # Title box
        title_box = customtkinter.CTkFrame(
            panel, corner_radius=8, fg_color=("gray80", "gray22")
        )
        title_box.pack(fill="x", padx=6, pady=4)
        customtkinter.CTkLabel(
            title_box,
            text=f"Race #{race_number}",
            font=customtkinter.CTkFont(size=22, weight="bold"),
        ).pack(pady=8)

        if detail["teams"]:
            self._add_section_title(panel, "TEAM RESULT")
            self._build_team_table(panel, detail["teams"])

        if detail["results"]:
            self._add_section_title(panel, "SCOREBOARD")
            self._build_player_table(panel, detail["results"])

    def _render_standings(self, race_number):
        panel = self.standings_panel["scroll"]
        self._clear_children(panel)
        if self.current_war_id is None:
            self._add_message(panel, "Select a war to see standings.")
            return

        teams = persistence.get_team_standings_up_to(
            self.current_war_id, race_number
        )
        players = persistence.get_player_standings_up_to(
            self.current_war_id, race_number
        )

        title_box = customtkinter.CTkFrame(
            panel, corner_radius=8, fg_color=("gray80", "gray22")
        )
        title_box.pack(fill="x", padx=6, pady=4)
        customtkinter.CTkLabel(
            title_box,
            text=f"STANDINGS — RACE {race_number}",
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

    def _build_team_table(self, parent, teams):
        table = customtkinter.CTkFrame(parent, corner_radius=6, fg_color="transparent")
        table.pack(fill="x", padx=10, pady=(0, 6))
        table.grid_columnconfigure(0, weight=1, minsize=60)
        table.grid_columnconfigure(1, weight=0, minsize=40)
        table.grid_columnconfigure(2, weight=0, minsize=40)

        for col, text in enumerate(("TEAM", "PTS", "NET")):
            customtkinter.CTkLabel(
                table,
                text=text,
                font=customtkinter.CTkFont(size=12, weight="bold"),
                text_color=("gray40", "gray70"),
                anchor="w",
            ).grid(row=0, column=col, padx=8, pady=(2, 2), sticky="w")

        for i, team in enumerate(teams, start=1):
            net = team["net_points"]
            sign = "+" if net > 0 else ""
            net_color = (
                ("#1e8e3e", "#6bc077")
                if net > 0
                else (("#c62828", "#ef9a9a") if net < 0 else "gray")
            )
            customtkinter.CTkLabel(
                table,
                text=team["team_tag"],
                anchor="w",
                font=customtkinter.CTkFont(weight="bold"),
            ).grid(row=i, column=0, padx=8, pady=2, sticky="w")
            customtkinter.CTkLabel(
                table, text=str(team["points"]), anchor="w"
            ).grid(row=i, column=1, padx=8, pady=2, sticky="w")
            customtkinter.CTkLabel(
                table, text=f"{sign}{net}", anchor="w", text_color=net_color
            ).grid(row=i, column=2, padx=8, pady=2, sticky="w")

    def _build_player_table(self, parent, results):
        table = customtkinter.CTkFrame(parent, corner_radius=6, fg_color="transparent")
        table.pack(fill="x", padx=10, pady=(0, 6))
        table.grid_columnconfigure(0, weight=0, minsize=40)
        table.grid_columnconfigure(1, weight=1)
        table.grid_columnconfigure(2, weight=0, minsize=50)

        for col, text in enumerate(("POS", "PLAYER", "PTS")):
            customtkinter.CTkLabel(
                table,
                text=text,
                font=customtkinter.CTkFont(size=12, weight="bold"),
                text_color=("gray40", "gray70"),
                anchor="w",
            ).grid(row=0, column=col, padx=8, pady=(2, 2), sticky="w")

        for i, row in enumerate(results, start=1):
            customtkinter.CTkLabel(
                table, text=str(row["position"]), anchor="w", text_color="gray"
            ).grid(row=i, column=0, padx=8, pady=2, sticky="w")

            name_cell = customtkinter.CTkFrame(table, fg_color="transparent")
            name_cell.grid(row=i, column=1, padx=8, pady=2, sticky="w")
            customtkinter.CTkLabel(name_cell, text=row["player_name"], anchor="w").pack(
                side="left"
            )
            if row["is_bot"]:
                customtkinter.CTkLabel(
                    name_cell, text="(Bot)", text_color="gray", anchor="w"
                ).pack(side="left", padx=(4, 0))

            customtkinter.CTkLabel(
                table, text=str(row["points"]), anchor="e"
            ).grid(row=i, column=2, padx=8, pady=2, sticky="e")

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
    # Race list
    # ------------------------------------------------------------------

    def _populate_races(self, races):
        for widget in self.race_list.winfo_children():
            widget.destroy()
        self.race_buttons = {}
        self.delete_buttons = {}
        self.selected_race = None

        for race in races:
            label = f"Race {race['race_number']}"
            if race.get("label"):
                label += f" — {race['label']}"

            row = customtkinter.CTkFrame(self.race_list, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)

            rn = race["race_number"]
            btn = customtkinter.CTkButton(
                row,
                text=label,
                anchor="w",
                height=32,
                fg_color="transparent",
                command=lambda rn=rn: self._select_race(rn),
            )
            btn.grid(row=0, column=0, sticky="ew")

            delete_btn = customtkinter.CTkButton(
                row,
                text="✕",
                width=28,
                height=32,
                fg_color="transparent",
                hover_color="#a52a2a",
                text_color=("gray40", "gray70"),
                command=lambda rn=rn: self._confirm_delete_race(rn),
            )
            delete_btn.grid(row=0, column=1, padx=(4, 0))

            self.race_buttons[rn] = btn
            self.delete_buttons[rn] = delete_btn

    def _select_race(self, race_number):
        self.selected_race = race_number
        for rn, btn in self.race_buttons.items():
            btn.configure(fg_color=("gray75", "gray25") if rn == race_number else "transparent")
        self._render_detail(race_number)
        self._render_standings(race_number)

    def _confirm_delete_race(self, race_number):
        ConfirmDialog(
            self,
            title="Delete race",
            message=f"Delete race #{race_number}?\n"
                    "Its results and standings contribution will be removed.",
            on_confirm=lambda: self._delete_race(race_number),
        )

    def _delete_race(self, race_number):
        if self.current_war_id is None:
            return
        persistence.delete_race(self.current_war_id, race_number)

        races = self._fetch_races(self.current_war_id)
        self._populate_races(races)
        if races:
            self._select_race(races[0]["race_number"])
        else:
            self._clear_children(self.detail_panel["scroll"])
            self._clear_children(self.standings_panel["scroll"])
            self._add_message(
                self.detail_panel["scroll"],
                "No races left in this war.",
            )
            self._add_message(self.standings_panel["scroll"], "(no standings yet)")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_team_result(results):
        """Aggregate per-team points from a scoreboard and compute net results.

        Used for races saved before team_race_results existed. Returns a list
        of dicts (team_tag, points, net_points) ordered by points, or empty
        if no team tag is configured for any player.
        """
        from lakituai import config, logic

        cfg = config.load_config()
        team_points = {}
        for row in results:
            tag = logic.extract_team_tag(row["player_name"], cfg.team_tags)
            if tag:
                team_points[tag] = team_points.get(tag, 0) + row["points"]

        net_points = logic.build_net_points(team_points)
        return [
            {"team_tag": tag, "points": pts, "net_points": net_points.get(tag, 0)}
            for tag, pts in sorted(team_points.items(), key=lambda kv: kv[1], reverse=True)
        ]

    @staticmethod
    def _clear_children(frame):
        for widget in frame.winfo_children():
            widget.destroy()

    @staticmethod
    def _add_message(parent, text):
        customtkinter.CTkLabel(
            parent, text=text, text_color="gray", justify="left", anchor="w"
        ).pack(fill="x", padx=10, pady=6)
