"""Players tab for the LakituAI GUI.

Shows every registered player grouped by nothing in particular, each with
Edit / Delete actions, plus an "add player" form and a team tag manager.

Changes go straight to the JSON config files through player_management
(and edit also renames the player in the database), so the CLI and the
chatbot see the same roster.
"""

import customtkinter

from lakituai import config, player_management
from lakituai.chat import tools


def fix_dialog_to_window(dialog, master):
    """Anchor ``dialog`` to the main window: transient, modal, centered.

    Tk dialogs otherwise open wherever the OS puts them, which can be off to
    the side or hidden behind the main window. Making the dialog transient to
    the app window and grabbing input keeps it on top and centered over it.

    Ordering matters here: the grab is what actually makes the window manager
    map the dialog at the requested position, and ``focus_set`` must not be
    called until the dialog is already mapped (it leaves the dialog stuck at
    Tk's "not yet placed" position on some window managers). The position is
    re-asserted once more shortly after mapping so window managers that race
    on the initial map still end up with the dialog centered on the window.
    """
    parent = master.winfo_toplevel()
    dialog.transient(parent)
    dialog.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
    x = max(0, min(x, dialog.winfo_screenwidth() - dialog.winfo_width()))
    y = max(0, min(y, dialog.winfo_screenheight() - dialog.winfo_height()))
    dialog.geometry(f"+{x}+{y}")
    dialog.lift()
    dialog.grab_set()

    def _reassert_position():
        dialog.geometry(f"+{x}+{y}")
        dialog.lift()

    # Destroying the dialog cancels its pending ``after`` callbacks, so this
    # is safe even if the user closes it before the timer fires.
    dialog.after(30, _reassert_position)


class PlayersTab(customtkinter.CTkFrame):
    """Roster management: list, add, edit and remove players and team tags."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.players = []
        self.team_tags = []
        self.player_rows = {}
        self.tag_buttons = {}
        self._build()
        self.refresh()

    def _build(self):
        self.grid_columnconfigure(0, weight=6, minsize=560)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top bar: title + refresh
        top = customtkinter.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 5))
        top.grid_columnconfigure(0, weight=1)

        self.title_label = customtkinter.CTkLabel(top, text="Players", anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.refresh_button = customtkinter.CTkButton(
            top, text="⟳", width=40, command=self.refresh
        )
        self.refresh_button.grid(row=0, column=1, padx=5)

        # Left: player list
        self.player_list = customtkinter.CTkScrollableFrame(self)
        self.player_list.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        self.player_list.grid_columnconfigure(0, weight=1)

        # Right: compact team tags on top, add player form right below it
        right = customtkinter.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=0)
        right.grid_rowconfigure(2, weight=0)
        right.grid_rowconfigure(3, weight=1)

        self._build_tags_panel(right)
        self._build_add_form(right)

        # Feedback line
        self.status_label = customtkinter.CTkLabel(self, text="", anchor="w")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))

    def _build_add_form(self, parent):
        form = customtkinter.CTkFrame(parent, corner_radius=8)
        form.grid(row=2, column=0, sticky="ew", padx=0, pady=10)
        form.grid_columnconfigure(1, weight=1)

        customtkinter.CTkLabel(form, text="Add player", anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4)
        )

        customtkinter.CTkLabel(form, text="Tag:").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.add_tag_menu = customtkinter.CTkOptionMenu(form, values=["(none)"], width=120)
        self.add_tag_menu.grid(row=1, column=1, columnspan=2, sticky="w", padx=(0, 10), pady=4)

        customtkinter.CTkLabel(form, text="Name:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.add_name_entry = customtkinter.CTkEntry(form, placeholder_text="Player name")
        self.add_name_entry.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=4)
        self.add_name_entry.bind("<Return>", lambda event: self._add_player())

        self.add_button = customtkinter.CTkButton(form, text="Add", command=self._add_player)
        self.add_button.grid(row=2, column=2, padx=(0, 10), pady=4)

    def _build_tags_panel(self, parent):
        panel = customtkinter.CTkFrame(parent, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        self._tags_panel = panel

        customtkinter.CTkLabel(panel, text="Team tags", anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4)
        )

        self.tag_list = None
        self._tag_wrapper = None

        bottom = customtkinter.CTkFrame(panel, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        bottom.grid_columnconfigure(0, weight=1)

        self.add_tag_entry = customtkinter.CTkEntry(bottom, placeholder_text="New tag")
        self.add_tag_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.add_tag_entry.bind("<Return>", lambda event: self._add_tag())

        self.add_tag_button = customtkinter.CTkButton(bottom, text="+", width=40, command=self._add_tag)
        self.add_tag_button.grid(row=0, column=1)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload players and team tags, then re-render the tab."""
        cfg = config.load_config()
        self.players = list(cfg.players)
        self.team_tags = list(cfg.team_tags)

        self.title_label.configure(text=f"Players ({len(self.players)})")

        tags = self.team_tags or ["(none)"]
        current = self.add_tag_menu.get()
        self.add_tag_menu.configure(values=tags)
        if current in tags:
            self.add_tag_menu.set(current)
        elif self.team_tags:
            self.add_tag_menu.set(self.team_tags[0])

        self._render_players()
        self._render_tags()

    def _render_players(self):
        for widget in self.player_list.winfo_children():
            widget.destroy()
        self.player_rows = {}

        if not self.players:
            customtkinter.CTkLabel(
                self.player_list, text="No players yet.", text_color="gray"
            ).pack(padx=10, pady=20)
            return

        cfg = config.load_config()
        for player in self.players:
            tag = config.extract_team_tag_from_game_config(player, cfg) or "?"
            row = customtkinter.CTkFrame(self.player_list, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)
            row.grid_columnconfigure(1, weight=1)

            customtkinter.CTkLabel(
                row, text=f"[{tag}]", width=64, anchor="w", text_color="gray"
            ).grid(row=0, column=0, padx=(8, 4), pady=4)

            customtkinter.CTkLabel(row, text=player, anchor="w").grid(
                row=0, column=1, sticky="w", pady=4
            )

            edit_btn = customtkinter.CTkButton(
                row, text="Edit", width=60, height=26, command=lambda p=player: self._open_edit(p)
            )
            edit_btn.grid(row=0, column=2, padx=4, pady=4)

            del_btn = customtkinter.CTkButton(
                row,
                text="Delete",
                width=70,
                height=26,
                fg_color="#a52a2a",
                hover_color="#8b1a1a",
                command=lambda p=player: self._confirm_delete(p),
            )
            del_btn.grid(row=0, column=3, padx=(0, 8), pady=4)

            self.player_rows[player] = row

    def _render_tags(self):
        self._ensure_tag_list_widget()
        for widget in self.tag_list.winfo_children():
            widget.destroy()
        self.tag_buttons = {}

        if not self.team_tags:
            customtkinter.CTkLabel(
                self.tag_list, text="No tags configured.", text_color="gray"
            ).pack(padx=10, pady=10)
            return

        for tag in self.team_tags:
            row = customtkinter.CTkFrame(self.tag_list, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)

            customtkinter.CTkLabel(row, text=tag, anchor="w").grid(
                row=0, column=0, sticky="w", padx=(8, 4), pady=4
            )

            remove_btn = customtkinter.CTkButton(
                row,
                text="✕",
                width=34,
                height=24,
                fg_color="#a52a2a",
                hover_color="#8b1a1a",
                command=lambda t=tag: self._confirm_remove_tag(t),
            )
            remove_btn.grid(row=0, column=1, padx=(0, 6), pady=4)

            self.tag_buttons[tag] = row

    def _ensure_tag_list_widget(self):
        """Build the tag list as a plain frame, or as a scrollable frame with
        a fixed height once there are more than 4 tags (so the panel does not
        grow unbounded)."""
        many = len(self.team_tags) > 4
        want_scroll = isinstance(self.tag_list, customtkinter.CTkScrollableFrame)

        if (many and not want_scroll) or (not many and want_scroll):
            if self.tag_list is not None:
                self.tag_list.destroy()
            if self._tag_wrapper is not None:
                self._tag_wrapper.destroy()
            self.tag_list = None
            self._tag_wrapper = None
        if self.tag_list is not None:
            return

        if many:
            wrapper = customtkinter.CTkFrame(self._tags_panel, corner_radius=6)
            wrapper.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
            wrapper.pack_propagate(False)
            wrapper.configure(height=170)

            self.tag_list = customtkinter.CTkScrollableFrame(wrapper, fg_color="transparent")
            self.tag_list.pack(fill="both", expand=True)
            self._tag_wrapper = wrapper
        else:
            self.tag_list = customtkinter.CTkFrame(self._tags_panel, corner_radius=6)
            self.tag_list.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
            self._tag_wrapper = None

        self.tag_list.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add_player(self):
        name = self.add_name_entry.get().strip()
        tag = self.add_tag_menu.get()
        if not name:
            self._set_status("Player name is empty.", error=True)
            return
        if tag in (None, "(none)"):
            self._set_status("Add a team tag first.", error=True)
            return

        msg = tools.add_player(name, tag)
        if "added successfully" in msg:
            self.add_name_entry.delete(0, "end")
            self._set_status(msg)
            self.refresh()
        else:
            self._set_status(msg, error=True)

    def _open_edit(self, player):
        EditPlayerDialog(self, player, self.team_tags)

    def _on_edit_saved(self, old_name, new_name):
        msg = tools.edit_player(old_name, new_name)
        if "renamed" in msg or "updated" in msg:
            self._set_status(msg)
            self.refresh()
        else:
            self._set_status(msg, error=True)

    def _confirm_delete(self, player):
        ConfirmDialog(
            self,
            title="Delete player",
            message=f"Remove '{player}' from the roster?",
            on_confirm=lambda: self._remove_player(player),
        )

    def _remove_player(self, player):
        success, msg = player_management.remove_player(player)
        self._set_status(msg, error=not success)
        self.refresh()

    def _add_tag(self):
        tag = self.add_tag_entry.get().strip()
        if not tag:
            self._set_status("Tag is empty.", error=True)
            return

        from lakituai.chat.tools import add_team_tag

        msg = add_team_tag(tag)
        if "already exists" in msg:
            self._set_status(msg, error=True)
            return
        self.add_tag_entry.delete(0, "end")
        self._set_status(msg)
        self.refresh()

    def _confirm_remove_tag(self, tag):
        ConfirmDialog(
            self,
            title="Remove tag",
            message=f"Remove team tag '{tag}'? Players using it will keep their names.",
            on_confirm=lambda: self._remove_tag(tag),
        )

    def _remove_tag(self, tag):
        from lakituai.chat.tools import remove_team_tag

        msg = remove_team_tag(tag)
        self._set_status(msg, error="not found" in msg)
        self.refresh()

    def _set_status(self, message, error=False):
        self.status_label.configure(
            text=message,
            text_color="#ff6b6b" if error else ("#2e7d32", "#8bc34a"),
        )


class EditPlayerDialog(customtkinter.CTkToplevel):
    """Small dialog to rename a player (base name + team tag)."""

    def __init__(self, master, player, team_tags):
        super().__init__(master)
        self.player = player
        self.team_tags = list(team_tags)
        self._tab = master

        self.title("Edit player")
        self.geometry("340x200")
        self.resizable(False, False)

        cfg = config.load_config()
        self.current_tag = config.extract_team_tag_from_game_config(player, cfg)

        base = player
        if self.current_tag:
            base = player[len(self.current_tag):].lstrip(" .")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        customtkinter.CTkLabel(self, text="Current:").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4)
        )
        customtkinter.CTkLabel(self, text=player, anchor="w").grid(
            row=0, column=1, sticky="w", padx=12, pady=(12, 4)
        )

        customtkinter.CTkLabel(self, text="Name:").grid(
            row=1, column=0, sticky="w", padx=12, pady=4
        )
        self.name_entry = customtkinter.CTkEntry(self)
        self.name_entry.insert(0, base)
        self.name_entry.grid(row=1, column=1, sticky="ew", padx=12, pady=4)

        customtkinter.CTkLabel(self, text="Tag:").grid(
            row=2, column=0, sticky="w", padx=12, pady=4
        )
        tags = self.team_tags or ["(none)"]
        self.tag_menu = customtkinter.CTkOptionMenu(self, values=tags, width=120)
        if self.current_tag:
            self.tag_menu.set(self.current_tag)
        self.tag_menu.grid(row=2, column=1, sticky="w", padx=12, pady=4)

        buttons = customtkinter.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=2, sticky="se", padx=12, pady=12)

        customtkinter.CTkButton(
            buttons, text="Cancel", width=80, command=self.destroy
        ).pack(side="right", padx=4)
        customtkinter.CTkButton(
            buttons, text="Save", width=80, command=self._save
        ).pack(side="right", padx=4)

        fix_dialog_to_window(self, master)

    def _save(self):
        base = self.name_entry.get().strip()
        tag = self.tag_menu.get()
        if not base:
            return
        if tag in (None, "(none)"):
            return

        if base.lower().startswith(tag.lower()):
            full = base
        else:
            full = f"{tag} {base}"

        self._tab._on_edit_saved(self.player, full)
        self.destroy()


class ConfirmDialog(customtkinter.CTkToplevel):
    """Simple yes/no confirmation dialog."""

    def __init__(self, master, title, message, on_confirm):
        super().__init__(master)
        self.title(title)
        self.geometry("360x150")
        self.resizable(False, False)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        customtkinter.CTkLabel(self, text=message, wraplength=320, justify="left").grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 4)
        )

        buttons = customtkinter.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=1, column=0, sticky="se", padx=12, pady=12)

        customtkinter.CTkButton(
            buttons, text="Cancel", width=90, command=self.destroy
        ).pack(side="right", padx=4)
        customtkinter.CTkButton(
            buttons,
            text="Confirm",
            width=90,
            fg_color="#a52a2a",
            hover_color="#8b1a1a",
            command=lambda: self._confirmed(on_confirm),
        ).pack(side="right", padx=4)

        fix_dialog_to_window(self, master)

    def _confirmed(self, on_confirm):
        self.destroy()
        on_confirm()
