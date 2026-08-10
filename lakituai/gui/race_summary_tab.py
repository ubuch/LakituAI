"""Race Summary tab for the LakituAI GUI.

Shows, for the selected war:
- a clickable list of races (with the winner of each),
- the detail of the selected race (team result with net points + scoreboard),
- the cumulative standings (teams and players).

The war selector defaults to the current war (current_war.json).
"""

import customtkinter

from lakituai import persistence, war_manager


class RaceSummaryTab(customtkinter.CTkFrame):
    """Race list + race detail + cumulative standings for a war."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        persistence.init_db()

        self.wars = []
        self.current_war_id = None
        self.race_buttons = {}
        self.selected_race = None

        self._build()
        self.refresh()

    def _build(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
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

        # Left: race list
        self.race_list = customtkinter.CTkScrollableFrame(self, width=230)
        self.race_list.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        self.race_list.grid_columnconfigure(0, weight=1)

        # Right: detail (top) + standings (bottom)
        right = customtkinter.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=3)
        right.grid_rowconfigure(1, weight=2)

        self.detail_text = customtkinter.CTkTextbox(right, wrap="word", state="disabled")
        self.detail_text.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        self.standings_text = customtkinter.CTkTextbox(right, wrap="word", state="disabled")
        self.standings_text.grid(row=1, column=0, sticky="nsew")

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
            self._set_text(self.detail_text, "No wars found yet.")
            self._set_text(self.standings_text, "")
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
        self._render_standings()

        races = self._fetch_races(self.current_war_id)
        self._populate_races(races)
        if races:
            self._select_race(races[0]["race_number"])
        else:
            self._set_text(
                self.detail_text,
                "No races saved for this war yet.\n\n"
                "Process a screenshot from the CLI to add races.",
            )

    def _fetch_races(self, war_id):
        conn = persistence.sqlite3.connect(str(persistence.DB_PATH))
        conn.row_factory = persistence.sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.race_number,
                   (SELECT rr.player_name FROM race_results rr
                    WHERE rr.race_id = r.id AND rr.position = 1) AS winner
            FROM races r
            WHERE r.war_id = ?
            ORDER BY r.race_number
            """,
            (war_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"race_number": r["race_number"], "winner": r["winner"]} for r in rows]

    def _fetch_race_detail(self, war_id, race_number):
        conn = persistence.sqlite3.connect(str(persistence.DB_PATH))
        conn.row_factory = persistence.sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM races WHERE war_id = ? AND race_number = ?",
            (war_id, race_number),
        )
        race = cursor.fetchone()
        if not race:
            conn.close()
            return f"Race #{race_number} not found."

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

        lines = [f"Race #{race_number}", "=" * 26, ""]

        if teams:
            lines.append("TEAM RESULT:")
            for team in teams:
                sign = "+" if team["net_points"] >= 0 else ""
                lines.append(
                    f"  {team['team_tag']:10s}: {team['points']:3d} pts ({sign}{team['net_points']})"
                )
            lines.append("")

        lines.append("SCOREBOARD:")
        for row in results:
            lines.append(
                f"  P{row['position']:2d}  {row['points']:2d} pts  {row['player_name']}"
            )

        return "\n".join(lines)

    def _render_standings(self):
        if self.current_war_id is None:
            self._set_text(self.standings_text, "Select a war to see standings.")
            return

        teams = persistence.get_team_standings(self.current_war_id)
        players = persistence.get_player_standings(self.current_war_id)

        lines = ["STANDINGS", "=" * 26, ""]
        if teams:
            lines.append("TEAMS:")
            for team, pts in teams.items():
                lines.append(f"  {team:10s}: {pts:3d} pts")
            lines.append("")
        if players:
            lines.append("PLAYERS:")
            for player, pts in players.items():
                lines.append(f"  {player:20s}: {pts:3d} pts")
        else:
            lines.append("  (no data yet)")

        self._set_text(self.standings_text, "\n".join(lines))

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _populate_races(self, races):
        for widget in self.race_list.winfo_children():
            widget.destroy()
        self.race_buttons = {}
        self.selected_race = None

        for race in races:
            winner = f" — {race['winner']}" if race["winner"] else ""
            btn = customtkinter.CTkButton(
                self.race_list,
                text=f"Race {race['race_number']}{winner}",
                anchor="w",
                height=32,
                fg_color="transparent",
                command=lambda rn=race["race_number"]: self._select_race(rn),
            )
            btn.pack(fill="x", padx=4, pady=2)
            self.race_buttons[race["race_number"]] = btn

    def _select_race(self, race_number):
        self.selected_race = race_number
        for rn, btn in self.race_buttons.items():
            btn.configure(fg_color=("gray75", "gray25") if rn == race_number else "transparent")
        detail = self._fetch_race_detail(self.current_war_id, race_number)
        self._set_text(self.detail_text, detail)

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
    def _set_text(textbox, text):
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")
