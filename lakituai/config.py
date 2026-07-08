"""Configuration management for LakituAI.

Handles loading and managing game characters (bots), players, team tags, and
scoring rules. Supports loading from JSON files or using in-memory defaults.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
BOTS_CONFIG_PATH = CONFIG_DIR / "bots.json"
PLAYERS_CONFIG_PATH = CONFIG_DIR / "players.json"


DEFAULT_BOTS = (
    "Mario",
    "Luigi",
    "Peach",
    "Bowser",
    "Yoshi",
    "Toad",
    "Daisy",
    "Rosalina",
    "Estela",
    "Donkey Kong",
    "Wario",
    "Koopa",
    "Pauline",
    "Waluigi",
    "Toadette",
    "Baby Mario",
    "Baby Luigi",
    "Baby Peach",
    "Baby Daisy",
    "Baby Rosalina",
    "Baby Estela",
    "Bowser Jr",
    "Lakitu",
    "King Boo",
    "Shy Guy",
    "Birdo",
    "Dry Bones",
    "Huesitos",
    "Wiggler",
    "Floruga",
    "Hammer Bro",
    "Hermano Martillo",
    "Chargin' Chuck",
    "Placapum",
    "Nabbit",
    "Caco Gazapo",
    "Monty Mole",
    "Topo Monty",
    "Goomba",
    "Piranha Plant",
    "Planta Piraña",
    "Pianta",
    "Spike",
    "Escupico",
    "Cow",
    "Moo Moo",
    "Pokey",
    "Swoop",
    "Biddybud",
    "Para-Biddybud",
    "Biddybud alado",
    "Penguin",
    "Pingüino",
    "Sidestepper",
    "Snowman",
    "Hombre de Nieve",
    "Cataquack",
    "Catacuac",
    "Fish Bone",
    "Fishbone",
    "Dolphin",
    "Delfín",
    "Peepa",
    "Bat",
    "Murciélago",
    "Stingby",
    "Abejorro",
    "Rocky Wrench",
    "Coin Coffer",
    "Cheep Cheep",
    "Conkdor",
)

DEFAULT_PLAYERS = (
    "RK AxeeL",
    "ne.ths",
    "RK ivanchu",
    "ne.LOLmdr",
    "RK Aketx",
    "ne.popoff",
    "ne.crr",
    "RK Kevo",
    "ne.KIRIO",
    "RK jonz",
    "ne.starlow",
    "RK César",
)

DEFAULT_TEAM_TAGS = ("RK", "ne")

DEFAULT_POINTS_BY_POSITION = (15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)


@dataclass
class GameConfig:
    """Complete game configuration including players, bots, and scoring rules.
    
    Attributes:
        bots: Sequence of playable character names that can appear in scoreboards.
        players: Sequence of actual player names that can score points.
        team_tags: Sequence of team identifier prefixes/suffixes (e.g., "RK", "ne").
        points_by_position: Tuple of points awarded for each race position.
        match_threshold: Minimum fuzzy match score (0-100) to accept a player match.
        bot_match_threshold: Minimum fuzzy match score (0-100) to accept a bot match.
    """

    bots: Sequence[str] = field(default_factory=lambda: DEFAULT_BOTS)
    players: Sequence[str] = field(default_factory=lambda: DEFAULT_PLAYERS)
    team_tags: Sequence[str] = field(default_factory=lambda: DEFAULT_TEAM_TAGS)
    points_by_position: tuple[int, ...] = field(default_factory=lambda: DEFAULT_POINTS_BY_POSITION)
    match_threshold: int = 70
    bot_match_threshold: int = 90


def load_json_list(path: Path, fallback: Sequence[str]) -> Sequence[str]:
    """Load a JSON array from file, returning fallback if file doesn't exist."""
    if not path.exists():
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, IOError):
        pass
    return fallback


def save_json_list(path: Path, items: Sequence[str]) -> None:
    """Save a list to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(items), f, indent=2, ensure_ascii=False)


def load_config(
    bots_path: Path = BOTS_CONFIG_PATH,
    players_path: Path = PLAYERS_CONFIG_PATH,
) -> GameConfig:
    """Load configuration from JSON files with built-in defaults as fallback.
    
    Attempts to load bots and players from JSON config files. If files don't exist
    or are invalid, uses the hardcoded defaults. Team tags and scoring rules are
    always set to defaults.
    
    Args:
        bots_path: Path to JSON file containing bot character names.
        players_path: Path to JSON file containing player names.
    
    Returns:
        GameConfig instance with loaded or default values.
    """
    bots = load_json_list(bots_path, DEFAULT_BOTS)
    players = load_json_list(players_path, DEFAULT_PLAYERS)
    
    return GameConfig(
        bots=bots,
        players=players,
        team_tags=DEFAULT_TEAM_TAGS,
        points_by_position=DEFAULT_POINTS_BY_POSITION,
    )


def save_config(
    config: GameConfig,
    bots_path: Path = BOTS_CONFIG_PATH,
    players_path: Path = PLAYERS_CONFIG_PATH,
) -> None:
    """Save current configuration to JSON files.
    
    Args:
        config: GameConfig instance to save.
        bots_path: Path where bot names will be saved.
        players_path: Path where player names will be saved.
    """
    save_json_list(bots_path, config.bots)
    save_json_list(players_path, config.players)


def create_default_config_files() -> None:
    """Create default configuration JSON files in the config directory.
    
    Useful for first-time setup or to reset to defaults.
    """
    save_json_list(BOTS_CONFIG_PATH, DEFAULT_BOTS)
    save_json_list(PLAYERS_CONFIG_PATH, DEFAULT_PLAYERS)


def extract_team_tag_from_game_config(
    player_name: str,
    config_obj: GameConfig,
) -> str | None:
    """Extract a team tag from a player name using current game config.
    
    Args:
        player_name: Name of the player to check.
        config_obj: GameConfig instance with team tags.
    
    Returns:
        The team tag if found, None otherwise.
    """
    from lakituai import logic
    
    normalized_player = logic.normalize_text(player_name)
    sorted_tags = sorted(
        config_obj.team_tags,
        key=lambda tag: len(logic.normalize_text(tag)),
        reverse=True,
    )
    
    for team_tag in sorted_tags:
        normalized_tag = logic.normalize_text(team_tag)
        if normalized_player.startswith(normalized_tag):
            return team_tag
        if normalized_player.endswith(normalized_tag):
            return team_tag
    
    return None
