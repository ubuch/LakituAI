# LakituAI - Project Summary & Handoff

## 🎯 Project Vision

**LakituAI** is a background application for Mario Kart World war tracking that:
1. **Detects** scoreboards in video streams (currently processes static screenshots)
2. **Extracts** player names via OCR (TrOCR transformer model)
3. **Matches** extracted names to actual player database using fuzzy matching
4. **Calculates** war standings with disconnect handling (bot detection)
5. **Persists** results for multi-race, multi-war tracking
6. **Provides** an interface (chat or CLI) to query standings and manage wars

**Long-term goal:** A headless daemon continuously monitoring a video stream, auto-detecting and processing scoreboards, with a chat interface for natural language queries about war standings.

---

## 🏗️ Architecture Decisions

### Stateless Worker + Shared Store Pattern
- **Each CLI invocation is independent** (no persistent process state in memory)
- **All state stored in SQLite** (`resources/wars.db`)
- **Enables horizontal scaling**: Can run multiple CLI calls in parallel, triggered by cron/inotify/webhooks
- **Restart-safe**: Crash doesn't lose data; just restart CLI with next image

### Single Database, Multiple Wars
- **SQLite schema** supports arbitrary number of wars ("wars")
- **Each war** has independent race counter (race #1, #2, #3 per war)
- **Cascade delete** available to remove entire wars with one command
- **Current war tracking** in `config/current_war.json` for convenience

### Dual Persistence Layer
- **Race JSON files** (`resources/results/race_n_TAG1-TAG2_YYYY_MM_DD.json`):
    - For transparency and debugging
    - Contains full OCR data, normalized text, fuzzy match scores
    - One file per race, discoverable by name pattern
- **SQLite database**:
    - For structured queries (standings, leaderboards, history)
    - For future multi-war aggregation
    - For efficient lookups and analytics

### OCR + Fuzzy Matching Pipeline
- **TrOCR (Microsoft's Vision Transformer)**: Extracts text from scoreboard rows
- **RapidFuzz WRatio scorer**: Matches garbled OCR text to known player names
    - 70% threshold for player matching
    - 90% threshold for bot detection (NPC character names)
- **Bot handling**: Detected bots reassign points to disconnected players

### Configurable Game Logic
- **Hardcoded defaults** in code (fallback if config missing)
- **JSON-based config** (`config/players.json`, `config/bots.json`) for easy modification
- **API functions** in `player_management.py` (add\_player, remove\_player, add\_bot, remove\_bot)
- **Future enhancement**: Chat integration to modify config at runtime

---

## ✅ What's Been Implemented

### 1. Core Processing Pipeline
**File: `lakituai/ocr.py` (120 lines)**
- `extract_scoreboard_rows()`: Crops 12 rows from screenshot, upscales 8x, converts to grayscale
- `run_ocr_on_row()`: Applies TrOCR transformer model to single row
- OCR output includes raw text, confidence/debugging info

**File: `lakituai/logic.py` (510 lines)**
- `build_scoreboard_results()`: Fuzzy-matches OCR names to players, handles bots, assigns points
- `add_race_to_standings()`: Updates cumulative standings (player + team points)
- `build_team_points()`: Aggregates points by team tag
- Constants loaded from JSON config at module initialization

### 2. Configuration System
**File: `lakituai/config.py` (185 lines)**
- `GameConfig` dataclass: Players, bots, team\_tags, points\_by\_position, fuzzy match thresholds
- `load_config()`: Reads JSON or returns hardcoded defaults
- `save_config()`: Persists user modifications to JSON

**Files:**
- `config/players.json`: Initial 12 players with team tags (RK, ne)
- `config/bots.json`: 71 Mario Kart character names (Spanish/English)
- `config/current_war.json`: Tracks active war name

### 3. Player/Bot Management API
**File: `lakituai/player_management.py` (144 lines)**
- `add_player(name, tag)`, `remove_player(name)`: Modify players list
- `add_bot(name)`, `remove_bot(name)`: Modify bots list
- `extract_team_tags()`: Identifies team affiliations from player names
- All changes persisted to JSON

### 4. SQLite Persistence Layer
**File: `lakituai/persistence.py` (460 lines)**
- **Schema:**
    - `war`: id, name, created\_at
    - `races`: id, war\_id, race\_number, image\_path, json\_path, created\_at
    - `race_results`: id, race\_id, player\_name, position, points
    - `player_standings`: war\_id, player\_name, total\_points, races\_played, last\_updated
    - `team_standings`: war\_id, team\_tag, total\_points, races\_played, last\_updated

- **Key functions:**
    - `init_db()`: Create schema (idempotent)
    - `get_or_create_war(name)`: Get or create war by name
    - `save_race()`: Insert race + all player results
    - `update_standings()`: Upsert cumulative points using ON CONFLICT
    - `get_player_standings()`, `get_team_standings()`, `get_races_played()`
    - `list_wars()`: List all wars with metadata
    - `delete_war()`: Cascade delete war + all data
    - `get_war_by_name()`: Lookup war ID by name

### 5. War Manager
**File: `lakituai/war_manager.py` (43 lines)**
- `load_current_war()`: Read active war from config
- `set_current_war(name)`: Save active war to config
- `get_war_display_name()`: Format display string

### 6. CLI Interface
**File: `lakituai/lakitu_ai.py` (310 lines)**
- **Image processing mode:**
```bash
python -m lakituai path/to/screenshot.jpg
  python -m lakituai --war "War 1" path/to/screenshot.jpg
  ```

- **War management:**
  ```bash
  python -m lakituai --list-wars
  python -m lakituai --delete-war 2
  ```

- **Features:**
    - Parse arguments with argparse
    - Validate image path (existence, format)
    - OCR + fuzzy matching pipeline
    - Save race JSON to `resources/results/`
    - Save race to SQLite
    - Update cumulative standings
    - Display war standings from DB

### 7. Comprehensive Test Suite
**40+ tests, all passing:**
- `tests/test_logic.py` (11 tests): Player matching, scoring, standings accumulation
- `tests/test_cli.py` (6 tests): Argument parsing, path validation, image format checking
- `tests/test_config.py` (2 tests): Config loading, JSON persistence
- `tests/test_player_management.py` (10 tests): Add/remove players/bots, team tag extraction
- `tests/test_persistence.py` (6 tests): DB initialization, race saving, standings accumulation, races_played counter
- `tests/test_war_manager.py` (4 tests): Load/set current war, display names

### 8. Documentation
- `SETUP.md`: Installation and environment setup guide
- `CLI_EXAMPLES.txt`: CLI usage examples and error handling reference
- `WAR_MANAGEMENT.md`: Multi-war feature documentation
- `README.md`: Project overview (to be completed)

### 9. Project Structure
```
LakituAI/
├── lakituai/
│   ├── __main__.py          # Entry point for `python -m lakituai`
│   ├── ocr.py               # TrOCR pipeline
│   ├── logic.py             # Game logic (matching, scoring)
│   ├── config.py            # Configuration system
│   ├── player_management.py # API for modifying players/bots
│   ├── persistence.py       # SQLite layer
│   ├── war_manager.py # War tracking
│   └── lakitu_ai.py         # CLI entry point & orchestration
├── config/
│   ├── players.json         # Player names + team tags
│   ├── bots.json            # NPC character names
│   └── current_war.json # Active war tracking
├── resources/
│   ├── screenshots/         # Input images (gitignore'd content)
│   ├── rows/                # Extracted OCR rows (gitignore'd content)
│   ├── results/             # Race JSON files (gitignore'd content)
│   └── war.db        # SQLite database (gitignore'd)
├── tests/
│   ├── test_logic.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_player_management.py
│   ├── test_persistence.py
│   └── test_war_manager.py
├── requirements.txt         # Pinned dependencies (9 packages)
├── .gitignore              # Excludes user data, .venv, build artifacts
└── setup.py                # Package configuration (if needed)
```

---

## 🔧 Technical Details

### Dependencies (Pinned Versions)
- `opencv-python==4.13.0.92`: Image processing
- `transformers==5.10.1`: HuggingFace TrOCR model
- `torch==2.12.0`: Deep learning framework
- `tokenizers==0.22.2`: Fast tokenizer backend
- `sentencepiece==0.2.1`: **Critical for transformer compatibility**
- `huggingface_hub==1.17.0`: Model downloading
- `rapidfuzz==3.14.5`: Fuzzy string matching
- `Pillow==12.2.0`: Image manipulation
- `torchvision==0.27.0`: Computer vision utilities

**Key issue resolved:** TrOCR requires `sentencepiece` for fast tokenizer backend. Without it, transformer instantiation fails.

### Fuzzy Matching Strategy
- **Player names** may be garbled by OCR (spacing, accent issues, typos)
- **RapidFuzz WRatio** compares full strings and gives percentage similarity (0-100)
- **70% threshold**: If best match < 70%, player marked as unknown
- **90% threshold**: Bot detection (NPC names like "Luigi", "Toad", "Daisy")
- **Retry logic**: If no match at 70%, retry at lower threshold (configurable)

### Race Numbering
- **Per-war**: Each war has independent counter (race 1, 2, 3)
- **Max-based**: Uses max(existing files) + 1, not simple count
    - Survives file deletions (doesn't reuse numbers)
- **Filename format**: `race_{n}_{TAG1}-{TAG2}_{YYYY_MM_DD}.json`
    - `{n}`: Race number within war
    - `{TAG1}-{TAG2}`: Two team tags (e.g., "RK-ne")
    - `{YYYY_MM_DD}`: Race date (UTC, without time)

### SQLite Concurrency
- Currently uses default settings (serialized access)
- Future enhancement: Enable WAL mode for better concurrent read access
- Safe for single CLI process per war (stateless design)

### Config System Fallback Chain
1. **JSON files** (`config/players.json`, `config/bots.json`)
2. **Hardcoded defaults** in code (71 bots, 12 initial players)
3. If JSON missing → loads defaults → auto-creates JSON on first save

---

## 📊 Current State

### What Works
✅ Process single scoreboard image → extract OCR → match players → calculate points  
✅ Save race results to JSON + SQLite  
✅ Accumulate standings across multiple races (within same war)  
✅ Manage multiple wars independently  
✅ Switch between wars with `--war` flag  
✅ List wars with metadata (races, teams, dates)  
✅ Delete wars with cascade delete  
✅ All 40+ tests passing  
✅ CLI with proper error handling and user feedback  
✅ Configuration system with JSON persistence  
✅ Add/remove players and bots via API  

### What Doesn't Work Yet
❌ Automatic screenshot detection from video stream (scope TBD)  
❌ Background daemon/watcher (no cron/inotify integration)  
❌ Chat interface for querying standings  
❌ Web scraping from Mario Kart Central  
❌ UI dashboard to visualize standings  
❌ Multi-user concurrent access (WAL mode not enabled)  
❌ Schema migration strategy for future DB updates  

### Known Limitations
- Race numbering resets per war (by design; allows war-specific numbering)
- No built-in way to modify players/bots via CLI (only API; chat will be next layer)
- HuggingFace warnings about unauthenticated requests (harmless; public models don't need token)
- Player/bot lists currently hardcoded; future scraping will augment from Mario Kart Central

---

## 🚀 Next Steps (Prioritized)

### Phase 1: Web Scraping (HIGH PRIORITY)
**Goal:** Augment hardcoded player list with candidates from Mario Kart Central

1. **Research Mario Kart Central structure**
    - Identify player directory or API
    - Determine how to extract player names and team affiliations
    - Handle pagination/rate limiting

2. **Implement scraper**
    - Create `scraper.py` module
    - Fetch active player list from MKC
    - Normalize names (accents, spacing, case) to match current format
    - Handle duplicates and conflicts

3. **Integrate with CLI**
    - Add `--refresh-players` flag
    - Auto-update `config/players.json` from scraping
    - Log scraping stats (added, updated, skipped)

4. **Fallback strategy**
    - If scraping fails, fall back to current hardcoded list
    - Don't break app if MKC is unreachablema

### Phase 2: Chat Interface (MEDIUM PRIORITY)
**Goal:** Natural language queries about standings and management

1. **Design chat API**
    - Commands: "who was 5th in race 3?", "team RK standings", "player Alpha history"
    - Expose `persistence.py` query functions as callable endpoints
    - Parsing: Either regex-based or lightweight LLM-based

2. **Implementation options**
    - **(A) CLI chatbot**: Interactive Python script, read-eval-print loop
    - **(B) HTTP server**: Flask/FastAPI endpoint, curl-friendly
    - **(C) Slack/Discord bot**: Third-party integration
    - Recommend: Start with (A), graduate to (B)

3. **Queries to support**
    - "standings" → show current war standings
    - "races" → list races in current war
    - "player {name}" → show player's score history
    - "team {tag}" → show team's aggregate score
    - "who was {place} in race {n}" → specific race details
    - "compare {player1} vs {player2}" → head-to-head stats

### Phase 3: UI Dashboard (MEDIUM PRIORITY)
**Goal:** Visual standings browser

1. **Technology choice**
    - **(A) Web**: React/Vue + FastAPI backend
    - **(B) CLI**: Rich/Typer for terminal UI
    - **(C) Desktop**: PyQt/Tkinter
    - Recommend: (B) for simplicity, (A) for polish

2. **Features**
    - List wars with details
    - Browse war standings (searchable/sortable)
    - View race history with OCR debug data
    - Export standings to CSV/PDF

### Phase 4: Background Automation (MEDIUM PRIORITY)
**Goal:** Continuous scoreboard detection without manual invocation

1. **Screenshot detection trigger**
    - **Option A**: inotify watcher on `resources/screenshots/` (Linux/WSL)
    - **Option B**: Cron job every N seconds (simple polling)
    - **Option C**: Integrate with streaming software (OBS plugin or HTTP endpoint)

2. **Race detection heuristics**
    - Distinguish scoreboards from other frames (ML classifier?)
    - Avoid duplicate processing of same frame
    - Handle consecutive frames (debounce/throttle)

3. **Implementation**
    - Daemon process that watches folder
    - On new image: call `python -m lakituai` with auto-detected war
    - Log results and errors

### Phase 5: Advanced Features (LOW PRIORITY - Future)
- Multi-user concurrent access (enable SQLite WAL mode)
- Schema versioning / auto-migration
- Rename war without data loss
- Compress/archive old wars
- Statistics and analytics (win rates, position distributions, etc.)
- Export to CSV, JSON, PDF, or spreadsheet
- Replay entire war (visual replay of standings over races)

---

## 🔄 Development Notes

### How to Test
```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
python -m unittest discover tests -v

# Process a single screenshot (default war)
python -m lakituai resources/screenshots/screenshot1.jpg

# Switch to different war
python -m lakituai --war "War 1" resources/screenshots/screenshot1.jpg

# List all wars
python -m lakituai --list-wars

# Delete war
python -m lakituai --delete-war 1
```

### Reset Database
```bash
rm resources/war.db
```
Next CLI invocation will create a fresh database with current schema.

### How to Add a Feature
1. Write tests first (TDD approach; all tests currently passing)
2. Implement feature in relevant module
3. Update tests if schema/API changed
4. Run: `python -m unittest discover tests -v`
5. Test manually: `python -m lakituai <args>`
6. Commit with descriptive message (1-2 lines for small changes, longer for features)

### Dependencies Installation
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Code Quality
- All modules documented (docstrings for functions and classes)
- Type hints used where helpful
- No external linters configured yet (can add ruff/black if needed)
- Tests cover all major code paths
- Error handling includes user-friendly messages

---

## 📝 Files Changed Summary

**New files created:**
- `lakituai/war_manager.py`: War tracking
- `tests/test_persistence.py`: Persistence tests
- `tests/test_war_manager.py`: War manager tests
- `WAR_MANAGEMENT.md`: War feature docs
- `PROJECT_SUMMARY.md` (this file): Handoff documentation

**Modified files:**
- `lakituai/lakitu_ai.py`: Rewritten from 31 → 310 lines; added CLI war management
- `lakituai/persistence.py`: Extended from 330 → 460 lines; added war query/delete functions
- `requirements.txt`: Pinned all versions (9 packages)
- `.gitignore`: Simplified (removed .gitkeep references)
- `plan.md`: Updated with completed tasks

---

## 🎓 Key Learnings & Decisions

1. **Stateless design scales better**: Each CLI invocation is independent; can parallelize or trigger from multiple sources without coordination overhead.

2. **SQLite is adequate for this scale**: Single process per war, reasonable data volume; WAL mode can be added later for concurrency.

3. **Fuzzy matching is essential**: OCR output is noisy; 70% WRatio threshold strikes a good balance between false positives and false negatives.

4. **Configuration via JSON is user-friendly**: Non-technical users can edit JSON; API layer lets chat interface modify at runtime.

5. **Race numbering per-war is cleaner**: Easier to discuss "race 3" within a war; global numbering would be confusing for users.

6. **Cascade delete is important**: Multi-war support requires safe cleanup; relational integrity prevents orphaned data.

---

## 📌 Passing This Off

When handing to another developer/AI:
1. **Start with:** This summary (PROJECT_SUMMARY.md)
2. **Then review:** `plan.md` for high-level context
3. **Read code in this order:**
    - `lakituai/logic.py`: Core game logic
    - `lakituai/persistence.py`: Database layer
    - `lakituai/lakitu_ai.py`: CLI orchestration
    - Individual tests for detailed behavior

4. **Environment setup:**
    - Python 3.12+ (tested on 3.14.2 in WSL)
    - Virtual environment: `.venv/`
    - Install: `pip install -r requirements.txt`
    - Run tests: `python -m unittest discover tests -v`

5. **Next immediate task:** Phase 1 (Web Scraping) is recommended as it unblocks Phase 2 (Chat Interface).

---

**Project Status:** ✅ Core functionality complete; architecture solid; ready for extended features  
**Last Updated:** 2026-07-14  
**Python Version:** 3.12+  
**Test Coverage:** 40+ tests, all passing
````