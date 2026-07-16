def list_players() -> str:
    """List all registered players with their team tags."""
    ...


def add_player(name: str, team_tag: str) -> str:
    """Add a new player to the roster.

    Args:
        name: Player name (e.g., 'ne.ths')
        team_tag: Team tag prefix (e.g., 'ne', 'RK')
    """
    ...


def remove_player(name: str) -> str:
    """Remove a player from the roster."""
    ...


def get_standings(war_name: str | None = None) -> str:
    """Get current war standings (player and team points).

    Args:
        war_name: War name. Uses current war if not specified.
    """
    ...


def get_race_details(race_number: int, war_name: str | None = None) -> str:
    """Get detailed results of a specific race."""
    ...


def list_wars() -> str:
    """List all wars with their metadata."""
    ...


def get_player_history(player_name: str) -> str:
    """Get a player's race-by-race history."""
    ...
