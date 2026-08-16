# LakituAI

Desktop assistant that keeps score of **Mario Kart World wars** automatically. You just play; the app handles the bookkeeping.

> Looking for the technical details? [Developer info ↓](#for-developers)

---

## For players

### What does it do?

LakituAI watches your screen while you play. When a race ends and the 12-player scoreboard appears, it detects it on its own, reads the player names, and records:

- **points per player** by position,
- the **team result** (net) for each race,
- the **war totals** (players and teams).

No manual typing: the scoreboard is read and saved automatically. If the stream *rewinds* and shows the same race again, the app detects it and does not double-count it.

> *add image: LakituAI main window with the sidebar open*

### Requirements

- **Windows 10** (the OS it's tested on). It should work on **Windows 11**. On Linux, macOS, or WSL it may not work well.
- For the **chat**: a GPU with **~6 GB of VRAM** is recommended (without a GPU the chat works but slower). The rest of the app works fine with or without a GPU.
- On first run, the app downloads the OCR model and, if you want to use the chat, the chat model too. This can take a few minutes.

### Installation

1. Open the repository on GitHub. On the right side you'll find the **Releases** section.
2. Download the **`LakituAI-Setup`** installer.
3. Run it and follow the steps. The installer:
   - installs LakituAI on your PC,
   - if you don't have **Ollama**, installs it and downloads the chat model (so chat works out of the box).

When it's done, open LakituAI from the desktop or Start Menu shortcut.

### First steps

1. Open the **Players** tab.
2. Add the players exactly as they appear in game (with their *team tag* if they belong to a team, e.g. `RK AxeeL` or `ne Bily`).
3. Go to **Auto Capture** and turn the switch on.
4. Play. The app handles the rest.

### How it works while you play

- LakituAI watches your **main screen** (monitor 1). The scoreboard must be fully visible; if it's partial or covered, it's ignored and the app waits for the next one.
- When a complete scoreboard is detected, it's captured, processed, and the image is saved under the **Screenshots** tab.
- Each war lasts a set number of races (12 by default). When it reaches the limit, the app **starts a new war automatically** (`War 2`, `War 3`, ...).
- You can switch the active war from the **Wars** tab.

### The window, tab by tab

| Tab | Purpose |
| --- | --- |
| **Chat** | Ask questions in plain language about players, races, and wars. |
| **Race Summary** | Per-race detail: team result, per-player points, and where the standings stood at that point. |
| **Wars** | War list, final results, create/delete wars, and pick the current war. |
| **Players** | Add, edit, or remove players and team tags. |
| **Screenshots** | Browse and delete the captures made by the auto mode. |
| **Auto Capture** | Turn the screen detector on or off. |

> *add image: Players tab with the player list and team tags*

> *add image: Auto Capture tab with the switch on*

> *add image: Race Summary tab with a race breakdown and cumulative standings*

> *add image: Wars tab with the war list and final results*

> *add image: Screenshots tab with the auto-captures*

### The chat

In the **Chat** tab you can ask questions in English (or Spanish) and the app answers with real war data. A few examples:

- "How many points does RK have?"
- "Who won race 3 of War 1?"
- "How many races has ne played?"
- "Show me the final result of the last war"

The chat runs on **Ollama**, which the installer sets up for you. If chat is unavailable (e.g. Ollama isn't running or the model hasn't been downloaded), the tab tells you what's missing.

**Install the chat model manually** (e.g. if the installer couldn't):

1. Download and install Ollama from <https://ollama.com/download>.
2. Open a terminal (PowerShell) and run:
   ```bash
   ollama pull qwen3:4b
   ```
3. Wait for the download to finish (~2.5 GB).
4. Restart LakituAI — the Chat tab will work.

> *add image: Chat tab with a question and its answer*

### Tips and common questions

- **The scoreboard isn't detected?** Make sure it's fully visible on the main screen and **Auto Capture** is on.
- **Extra races saved?** If the stream replayed a scoreboard, the app ignores it. If something slipped through, you can delete the capture from **Screenshots** and the race from **Wars**.
- **Weird scores?** Points by position are 15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1. If a bot (character) occupies a spot, its points go to the missing player on that team, so the team total stays consistent.
- **Your war isn't 12 races?** That's set in a config file (it's an advanced setting; if you need to change it, ask).

---

## For developers

### Running from source

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m lakituai --gui
```

### Command line

```bash
# Process a scoreboard screenshot (uses the current war)
python -m lakituai path/to/screenshot.jpg

# Process into a specific war (creates it if missing, and sets it current)
python -m lakituai --war "War 1" path/to/screenshot.jpg

# Save even if it looks like the last race being replayed
python -m lakituai --force path/to/screenshot.jpg

# Wars
python -m lakituai --list-wars
python -m lakituai --delete-war 2
python -m lakituai --delete-wars 1 2 3
python -m lakituai --delete-race "War 1" 5
python -m lakituai --reset-db

# Players and team tags
python -m lakituai --list-players
python -m lakituai --add-player "RK AxeeL"
python -m lakituai --list-team-tags
python -m lakituai --add-team-tag RK

# Other modes
python -m lakituai --gui        # launch the desktop GUI
python -m lakituai --chat       # interactive chat (requires Ollama)
python -m lakituai --daemon     # background scoreboard watcher
python -m lakituai --daemon-stop
python -m lakituai --feed path/to/img1.png path/to/img2.png
```

`--feed` runs only the scoreboard detector over static images (no OCR, no DB) and reports the saturated fraction and band/edge coverage vs the configured gate. It's the detector calibration tool.

### Architecture

- **Stateless workers, shared store**: every CLI/OCR run is independent; all state lives in SQLite and JSON. There's no orchestrating server.
- **Pipeline**: capture (daemon) → scoreboard detection (saturation gates per band + edge density) → crop + 8x upscale → TrOCR per row → fuzzy match → points → save JSON + SQLite → update standings.
- **Fuzzy matching**: RapidFuzz WRatio against the roster. The previous race's OCR text is kept as a secondary source so repeated, garbled readings match the same player; duplicates are resolved greedily (highest score keeps the row).
- **Bot rows**: if a spot is taken by a playable character (bot), its points go to the first missing player on that team, keeping team totals consistent through disconnects.
- **Rewind detection**: a fingerprint of `(position, recipient)` pairs plus the last saved race's timestamp tells a replayed scoreboard apart from a new race (90 s window, overridable with `--force`).
- **Auto-rollover**: when a war reaches its race limit (`races_per_war`, 12), the next race creates and activates the next war (`War N`) automatically.
- **Dual persistence**: race details are stored as readable JSON and standings in SQLite with `PRAGMA user_version` for future migrations.
- **runtime_paths**: resolves directories depending on whether running from source (repo root) or frozen (`%APPDATA%\LakituAI`).

### Configuration

The files in `config/` are created with defaults on first run.

| File | Content |
| --- | --- |
| `config/players.json` | Registered player names |
| `config/team_tags.json` | Team tags (e.g. `RK`, `ne`) |
| `config/bots.json` | Playable character names used to detect bot rows |
| `config/settings.json` | Game rules and daemon tuning |
| `config/current_war.json` | Name of the active war |

Defaults in `config/settings.json`: `points_by_position` = `(15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)`, `races_per_war` = `12`; daemon: `monitor` = `1`, `poll_interval_s` = `0.5`, `gate_fraction` = `0.60`, `complete_min_band` = `0.50`, `complete_min_edge` = `1.5`, `cooldown_s` = `90.0`, `save_captures`.

### Data layout

```
resources/
├── wars.db                # SQLite: wars, races, race_results, team_race_results, standings
├── screenshots/           # Daemon captures: auto_1.jpg, auto_2.jpg, ...
├── rows/                  # Extracted per-row OCR images (intermediate)
├── results/war_<id>/      # Race JSON: race_<n>_<TAG1>-<TAG2>_<YYYY_MM_DD>.json
├── daemon.log             # Daemon log
└── daemon.pid             # Daemon pid file
```

### Tests

```bash
python -m unittest discover -s tests
```

228 tests cover the CLI, config, logic (matching/scoring), player management, persistence (incl. schema versioning), war manager, chat tools and GUI.

### Project structure

```
lakituai/
├── __main__.py             # `python -m lakituai`
├── lakitu_ai.py            # CLI entry point and orchestration
├── logic.py                # Image preprocessing, matching, scoring
├── detect.py               # Scoreboard detection (saturation gates)
├── ocr.py                  # TrOCR integration
├── config.py               # JSON config loading/saving with defaults
├── player_management.py    # Player/bot roster API
├── persistence.py          # SQLite layer (+ schema versioning)
├── war_manager.py          # Current-war tracking
├── daemon.py               # Background screen watcher
├── runtime_paths.py        # Source vs frozen path resolution
├── chat/
│   ├── agents.py           # ChatSession, tool-calling loop, REPL
│   └── tools.py            # 19 callable tools (ALL_TOOLS)
└── gui/
    ├── app.py              # Main window, sidebar, geometry handling
    ├── chat_tab.py         # Chat tab + welcome screen + VRAM warning
    ├── race_summary_tab.py # Per-race detail + cumulative standings
    ├── wars_tab.py         # War list, info, final standings
    ├── players_tab.py      # Roster/team-tag management + dialogs
    ├── screenshots_tab.py  # Screenshot viewer + thumbnail rail
    ├── daemon_tab.py       # Auto Capture on/off switch
    └── hardware.py         # VRAM detection (nvidia-smi / Vulkan / torch)
config/                      # JSON config files (see above)
packaging/
├── launcher.py              # PyInstaller entry point (GUI or CLI)
├── installer.iss            # Inno Setup installer
├── installer/install_ollama.ps1
└── logo.ico
resources/                   # Runtime data (gitignored)
tests/                       # unittest suite (228 tests)
LakituAI.spec                # PyInstaller spec (Windows onedir)
requirements.txt             # Runtime dependencies (pinned)
requirements-build.txt       # Same pins minus torch (CPU wheel installed separately)
```

### Building the installer

The exe and installer are built from GitHub Actions (the **Actions** tab → **Build Windows exe + installer** → **Run workflow**), which runs PyInstaller with the CPU torch wheel plus Inno Setup and uploads the `LakituAI-Setup` installer. To build locally on Windows: `pip install -r requirements-build.txt pyinstaller`, `pyinstaller --clean --noconfirm LakituAI.spec`, then compile `packaging/installer.iss` with ISCC.
