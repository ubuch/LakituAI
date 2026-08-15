"""Configuration management for LakituAI.

Handles loading and managing game characters (bots), players, team tags, and
scoring rules. Supports loading from JSON files or using in-memory defaults.
"""

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from lakituai import detect, runtime_paths

CONFIG_DIR = runtime_paths.user_data_dir() / "config"
BOTS_CONFIG_PATH = CONFIG_DIR / "bots.json"
PLAYERS_CONFIG_PATH = CONFIG_DIR / "players.json"
TEAM_TAGS_CONFIG_PATH = CONFIG_DIR / "team_tags.json"
RULES_CONFIG_PATH = CONFIG_DIR / "settings.json"


DEFAULT_BOTS = (
    "Mario",
    "Luigi",
    "Peach",
    "Yoshi",
    "Toad",
    "Koopa Troopa",
    "Bowser",
    "Wario",
    "Waluigi",
    "Pauline",
    "Baby Mario",
    "Baby Luigi",
    "Baby Peach",
    "Baby Daisy",
    "Toadette",
    "Baby Rosalina",
    "Shy Guy",
    "Nabbit",
    "Piranha Plant",
    "Hammer Bro",
    "Monty Mole",
    "Goomba",
    "Sidestepper",
    "Cheep Cheep",
    "Dry Bones",
    "Wiggler",
    "Pokey",
    "Cow",
    "Stingby",
    "Snowman",
    "Penguin",
    "Para-Biddybud",
    "Daisy",
    "Rosalina",
    "Lakitu",
    "Bowser Jr",
    "Birdo",
    "King Boo",
    "Donkey Kong",
    "Spike",
    "Cataquack",
    "Pianta",
    "Rocky Wrench",
    "Conkdor",
    "Peepa",
    "Swoop",
    "Fish Bone",
    "Coin Coffer",
    "Dolphin",
    "Chargin' Chuck",
    "Koopa",
    "Bebé Mario",
    "Bebé Luigi",
    "Bebé Peach",
    "Bebé Daisy",
    "Bebé Estela",
    "Caco Gazapo",
    "Planta Piraña",
    "Hermano Martillo",
    "Topo Monty",
    "Cangrejo",
    "Huesitos",
    "Floruga",
    "Vaca",
    "Abejorro",
    "Muñeco de nieve",
    "Pingüi",
    "Marchimotas Alado",
    "Estela",
    "Rey Boo",
    "Bowsy",
    "Pinocuac",
    "Forestano",
    "Tortopo",
    "Picacóndor",
    "Fantasmirón",
    "Swooper",
    "Pezueso",
    "Monerrana",
    "Delfín",
    "Placapum",
)

DEFAULT_POINTS_BY_POSITION = (15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)


@dataclass
class DaemonConfig:
    """Background scoreboard watcher settings.

    Attributes:
        monitor: mss monitor index to capture (1 = first physical monitor).
        poll_interval_s: seconds between screen polls.
        gate_fraction: minimum fraction of the panel zone the scoreboard
            block must cover to count as a scoreboard.
        complete_min_band: every horizontal band of the zone must be at
            least this saturated (0-1) for the panel to count as settled.
        cooldown_s: seconds to ignore the screen after a capture.
    """

    monitor: int = 1
    poll_interval_s: float = 0.5
    gate_fraction: float = detect.DEFAULT_GATE_FRACTION
    complete_min_band: float = detect.DEFAULT_COMPLETE_MIN_BAND
    cooldown_s: float = 90.0


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
    players: Sequence[str] = field(default_factory=list)
    team_tags: Sequence[str] = field(default_factory=list)
    points_by_position: tuple[int, ...] = field(
        default_factory=lambda: DEFAULT_POINTS_BY_POSITION
    )
    match_threshold: int = 70
    bot_match_threshold: int = 90
    races_per_war: int = 12
    daemon: DaemonConfig = field(default_factory=DaemonConfig)


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
    team_tags_path: Path = TEAM_TAGS_CONFIG_PATH,
    rules_path: Path = RULES_CONFIG_PATH,
) -> GameConfig:
    """Load configuration from JSON files.

    Loads bots, players, and team tags from their respective JSON config files.
    Bots fall back to hardcoded defaults if the file is missing.
    Players and team tags default to empty lists if files are missing.

    Args:
        bots_path: Path to JSON file containing bot character names.
        players_path: Path to JSON file containing player names.
        team_tags_path: Path to JSON file containing team tag identifiers.
        rules_path: Path to JSON file containing rules settings.

    Returns:
        GameConfig instance with loaded or default values.
    """
    bots = load_json_list(bots_path, DEFAULT_BOTS)
    players = load_json_list(players_path, [])
    team_tags = load_json_list(team_tags_path, [])

    races_per_war = 12
    daemon_cfg = DaemonConfig()
    if rules_path.exists():
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                races_per_war = data.get("races_per_war", 12)
                daemon_data = data.get("daemon", {})
                if isinstance(daemon_data, dict):
                    daemon_cfg = DaemonConfig(
                        monitor=int(daemon_data.get("monitor", daemon_cfg.monitor)),
                        poll_interval_s=float(
                            daemon_data.get("poll_interval_s", daemon_cfg.poll_interval_s)
                        ),
                        gate_fraction=float(
                            daemon_data.get("gate_fraction", daemon_cfg.gate_fraction)
                        ),
                        complete_min_band=float(
                            daemon_data.get("complete_min_band", daemon_cfg.complete_min_band)
                        ),
                        cooldown_s=float(
                            daemon_data.get("cooldown_s", daemon_cfg.cooldown_s)
                        ),
                    )
        except Exception:
            pass

    return GameConfig(
        bots=bots,
        players=players,
        team_tags=team_tags,
        points_by_position=DEFAULT_POINTS_BY_POSITION,
        races_per_war=races_per_war,
        daemon=daemon_cfg,
    )


def save_config(
    config: GameConfig,
    bots_path: Path = BOTS_CONFIG_PATH,
    players_path: Path = PLAYERS_CONFIG_PATH,
    team_tags_path: Path = TEAM_TAGS_CONFIG_PATH,
    rules_path: Path = RULES_CONFIG_PATH,
) -> None:
    """Save current configuration to JSON files.

    Args:
        config: GameConfig instance to save.
        bots_path: Path where bot names will be saved.
        players_path: Path where player names will be saved.
        team_tags_path: Path where team tags will be saved.
        rules_path: Path where rules settings will be saved.
    """
    save_json_list(bots_path, config.bots)
    save_json_list(players_path, config.players)
    save_json_list(team_tags_path, config.team_tags)

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if rules_path.exists():
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            pass

    existing["races_per_war"] = config.races_per_war
    existing["daemon"] = {
        "monitor": config.daemon.monitor,
        "poll_interval_s": config.daemon.poll_interval_s,
        "gate_fraction": config.daemon.gate_fraction,
        "complete_min_band": config.daemon.complete_min_band,
        "cooldown_s": config.daemon.cooldown_s,
    }

    try:
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


def create_default_config_files() -> None:
    """Create default configuration JSON files in the config directory.

    Creates bots.json with hardcoded defaults and team_tags.json with empty list.
    Players.json is not created with defaults — it must be configured by the user.
    """
    save_json_list(BOTS_CONFIG_PATH, DEFAULT_BOTS)
    save_json_list(TEAM_TAGS_CONFIG_PATH, [])


def seed_config_files() -> None:
    """Seed default config files from the bundle on first run.

    When frozen, the read-only ``bots.json`` shipped inside the executable is
    copied into the per-user config directory so it can be edited later. Safe
    to call at every startup; existing user files are never overwritten.
    """
    if not runtime_paths.is_frozen():
        return
    bundled = runtime_paths.bundle_dir() / "config" / "bots.json"
    if bundled.exists() and not BOTS_CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, BOTS_CONFIG_PATH)


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
