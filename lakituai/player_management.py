"""Player and bot management for LakituAI.

Provides functions to add, remove, and list players and bot characters.
Changes are persisted to JSON configuration files.
"""

from pathlib import Path
from typing import Sequence

from lakituai import config


def add_player(
    player_name: str,
    players_path: Path = config.PLAYERS_CONFIG_PATH,
) -> tuple[bool, str]:
    """Add a new player to the active players list.
    
    Args:
        player_name: Name of the player to add (should include team tag).
        players_path: Path to the players configuration file.
    
    Returns:
        Tuple of (success: bool, message: str)
        - True if player was added
        - False if player already exists or validation fails
    """
    cfg = config.load_config(players_path=players_path)
    
    if player_name in cfg.players:
        return False, f"Player '{player_name}' already exists."
    
    team_tag = config.extract_team_tag_from_game_config(player_name, cfg)
    if not team_tag:
        return False, (
            f"Player '{player_name}' must have a team tag "
            f"({', '.join(cfg.team_tags)}) at start or end."
        )
    
    updated_players = list(cfg.players) + [player_name]
    cfg.players = updated_players
    config.save_config(cfg, players_path=players_path)
    
    return True, f"Player '{player_name}' added successfully."


def remove_player(
    player_name: str,
    players_path: Path = config.PLAYERS_CONFIG_PATH,
) -> tuple[bool, str]:
    """Remove a player from the active players list.
    
    Args:
        player_name: Name of the player to remove.
        players_path: Path to the players configuration file.
    
    Returns:
        Tuple of (success: bool, message: str)
        - True if player was removed
        - False if player doesn't exist
    """
    cfg = config.load_config(players_path=players_path)
    
    if player_name not in cfg.players:
        return False, f"Player '{player_name}' not found."
    
    updated_players = [p for p in cfg.players if p != player_name]
    cfg.players = updated_players
    config.save_config(cfg, players_path=players_path)
    
    return True, f"Player '{player_name}' removed successfully."


def get_players(
    players_path: Path = config.PLAYERS_CONFIG_PATH,
) -> Sequence[str]:
    """Get the current list of active players.
    
    Args:
        players_path: Path to the players configuration file.
    
    Returns:
        Sequence of player names.
    """
    cfg = config.load_config(players_path=players_path)
    return cfg.players


def add_bot(
    bot_name: str,
    bots_path: Path = config.BOTS_CONFIG_PATH,
) -> tuple[bool, str]:
    """Add a new bot character to the recognized bots list.
    
    Args:
        bot_name: Name of the bot character to add.
        bots_path: Path to the bots configuration file.
    
    Returns:
        Tuple of (success: bool, message: str)
        - True if bot was added
        - False if bot already exists
    """
    cfg = config.load_config(bots_path=bots_path)
    
    if bot_name in cfg.bots:
        return False, f"Bot '{bot_name}' already exists."
    
    updated_bots = list(cfg.bots) + [bot_name]
    cfg.bots = updated_bots
    config.save_config(cfg, bots_path=bots_path)
    
    return True, f"Bot '{bot_name}' added successfully."


def remove_bot(
    bot_name: str,
    bots_path: Path = config.BOTS_CONFIG_PATH,
) -> tuple[bool, str]:
    """Remove a bot character from the recognized bots list.
    
    Args:
        bot_name: Name of the bot character to remove.
        bots_path: Path to the bots configuration file.
    
    Returns:
        Tuple of (success: bool, message: str)
        - True if bot was removed
        - False if bot doesn't exist
    """
    cfg = config.load_config(bots_path=bots_path)
    
    if bot_name not in cfg.bots:
        return False, f"Bot '{bot_name}' not found."
    
    updated_bots = [b for b in cfg.bots if b != bot_name]
    cfg.bots = updated_bots
    config.save_config(cfg, bots_path=bots_path)
    
    return True, f"Bot '{bot_name}' removed successfully."


def get_bots(
    bots_path: Path = config.BOTS_CONFIG_PATH,
) -> Sequence[str]:
    """Get the current list of recognized bot characters.
    
    Args:
        bots_path: Path to the bots configuration file.
    
    Returns:
        Sequence of bot character names.
    """
    cfg = config.load_config(bots_path=bots_path)
    return cfg.bots
