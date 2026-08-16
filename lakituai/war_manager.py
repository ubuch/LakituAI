"""War management and selection.

Handles switching between wars, storing current war preference,
and providing a simple interface for war management.
"""

import json

from lakituai import runtime_paths

WAR_CONFIG_PATH = runtime_paths.user_data_dir() / "config" / "current_war.json"


def load_current_war() -> str:
    """Load the current war name from config.

    Returns:
        War name; defaults to "Default" if config doesn't exist.
    """
    try:
        if WAR_CONFIG_PATH.exists():
            with open(WAR_CONFIG_PATH, "r") as f:
                data = json.load(f)
                return data.get("current_war", "Default")
    except Exception:
        pass

    return "Default"


def set_current_war(name: str) -> None:
    """Set the current war name in config.

    Args:
        name: War name to set as current.
    """
    WAR_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = {"current_war": name}
    with open(WAR_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
