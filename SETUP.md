# LakituAI Setup Guide

## Prerequisites

- Python 3.12+ (I'm using Python 3.14.2 via pyenv)
- Virtual environment support (venv module)

## Installation

### 1. Activate Virtual Environment

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate.bat
```

**Linux/macOS/WSL:**
```bash
source venv/bin/activate
```

### 2. Install Dependencies

With the virtual environment activated:

```bash
pip install -r requirements.txt
```

This installs all required packages:
- `opencv-python`: Image processing
- `transformers`: TrOCR model for OCR
- `Pillow`: Image manipulation
- `rapidfuzz`: Fuzzy string matching for player detection
- `torch`: Deep learning framework for TrOCR

## Usage

### Running the CLI

Process a scoreboard screenshot:

```bash
# With venv activated:
python -m lakituai path/to/screenshot.jpg
```

### Examples

```bash
# Process a specific screenshot
python -m lakituai ~/races/race1.jpg

# Using relative path
python -m lakituai screenshots/screenshot1.png
```

### Output

The CLI will:
1. Extract scoreboard rows from the image
2. Run OCR on each row to detect player names
3. Match OCR results to actual player names
4. Calculate race points for each player/team
5. Print detailed results including:
   - Scoreboard details (position, player, points awarded)
   - Player standings
   - Team standings
   - Total races processed

## Running Tests

With the virtual environment activated:

```bash
python -m unittest discover tests -v
```

Individual test modules:

```bash
# Test CLI functionality
python -m unittest tests.test_cli -v

# Test core logic
python -m unittest tests.test_logic -v
```

## Project Structure

```
LakituAI/
├── config/
│   ├── bots.json           # Playable character list
│   └── players.json        # Active player list
├── lakituai/
│   ├── __init__.py
│   ├── __main__.py         # Package entry point
│   ├── lakitu_ai.py        # CLI implementation
│   ├── logic.py            # Core scoring logic
│   ├── ocr.py              # OCR integration
│   ├── config.py           # Configuration management
│   └── player_management.py # Player/bot management
├── resources/
│   └── screenshots/        # Input images
├── tests/
│   ├── test_cli.py         # CLI tests
│   └── test_logic.py       # Logic tests
├── requirements.txt        # Dependencies
└── venv/                   # Virtual environment (git-ignored)
```

## Configuration

### Modifying Players

Add a player programmatically:
```python
from lakituai import player_management
success, msg = player_management.add_player("RK NewPlayer")
print(msg)
```

Remove a player:
```python
success, msg = player_management.remove_player("RK AxeeL")
print(msg)
```

Get current players:
```python
players = player_management.get_players()
```

### Modifying Bots

Similarly, you can manage bot characters:
```python
from lakituai import player_management

player_management.add_bot("NewCharacter")
player_management.remove_bot("Mario")
bots = player_management.get_bots()
```

### Resetting to Defaults

```python
from lakituai import config
config.create_default_config_files()
```

## Development

### Code Organization

- **lakitu_ai.py**: CLI argument parsing and validation
- **logic.py**: Image processing, OCR coordination, player matching, scoring
- **config.py**: Configuration file loading/saving with defaults
- **player_management.py**: API for modifying player/bot lists
- **ocr.py**: TrOCR model integration

### Adding Tests

Create new test files in the `tests/` directory following the naming convention `test_*.py`.

Tests use Python's `unittest` framework with support for:
- Mocking external dependencies
- Temporary file creation for testing file I/O
- Asserting on both success and error cases

Run tests frequently to ensure code quality:
```bash
python -m unittest discover tests -v
```
