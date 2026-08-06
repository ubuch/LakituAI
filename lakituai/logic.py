"""Core image processing, matching, scoring, and standings logic for LakituAI."""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
from rapidfuzz import process, fuzz

from lakituai import config

BASE_W = 1920
BASE_H = 1080
NUMBER_OF_ROWS = 12
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_DIR = PROJECT_ROOT / "resources"
SCREENSHOTS_DIR = RESOURCES_DIR / "screenshots"
ROWS_DIR = RESOURCES_DIR / "rows"

# Load configuration from files, with hardcoded defaults as fallback
_LOADED_CONFIG = config.load_config()
POINTS_BY_POSITION = _LOADED_CONFIG.points_by_position
TEAM_TAGS = _LOADED_CONFIG.team_tags
BOT_NAMES = _LOADED_CONFIG.bots
BOT_MATCH_THRESHOLD = _LOADED_CONFIG.bot_match_threshold
PLAYERS = _LOADED_CONFIG.players
MATCH_THRESHOLD = _LOADED_CONFIG.match_threshold
RACES_PER_WAR = _LOADED_CONFIG.races_per_war


@dataclass(frozen=True)
class FuzzyMatch:
    """Best player candidate found for one OCR reading."""

    player_name: str
    score: float
    source: str


@dataclass(frozen=True)
class ScoreboardRowResult:
    """Structured result for a single scoreboard position."""

    row_number: int
    points: int
    ocr_text: str
    normalized_text: str
    matched_player: str
    points_recipient: str
    match_score: float
    match_source: str
    is_bot: bool = False
    is_missing_player: bool = False


@dataclass
class WarStandings:
    """Accumulated points across one or more races."""

    player_points: dict[str, int] = field(default_factory=dict)
    team_points: dict[str, int] = field(default_factory=dict)
    races_played: int = 0


def _get_image(path):
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return img


def _save_img(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def upscale_img(path):
    """Crop the scoreboard from a screenshot and upscale it for OCR."""

    img = _get_image(path)

    h, w = img.shape[:2]

    x1 = int(1269 * w / BASE_W)
    x2 = int(1664 * w / BASE_W)

    y1 = int(43 * h / BASE_H)
    y2 = int(956 * h / BASE_H)

    roi = img[y1:y2, x1:x2]

    upscaled = cv2.resize(roi, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)

    return upscaled


def convert_to_grayscale(img):
    """Convert an OpenCV BGR image to grayscale."""

    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def cut_scoreboard_rows(img, output_dir=ROWS_DIR, number_of_rows=NUMBER_OF_ROWS):
    """Split the scoreboard image into one image file per player row."""

    img_height = img.shape[0]
    row_height = img_height // number_of_rows
    row_paths = []

    for i in range(number_of_rows):
        y_top = i * row_height
        y_bot = (i + 1) * row_height

        row = img[y_top:y_bot, :]
        row_path = output_dir / f"row_{i + 1}.png"

        _save_img(row, row_path)
        row_paths.append(row_path)

    return row_paths


def prepare_scoreboard_rows(screenshot_path, output_dir=ROWS_DIR):
    """Create OCR-ready row images from a full-screen race screenshot."""

    image = upscale_img(screenshot_path)
    image_gray = convert_to_grayscale(image)
    return cut_scoreboard_rows(image_gray, output_dir)


def normalize_text(text):
    """Normalize OCR/player text for fuzzy matching."""

    return text.lower().replace(".", "").replace(" ", "")


def points_for_position(position, points_by_position=POINTS_BY_POSITION):
    """Return the race points awarded to a finishing position."""

    if position < 1 or position > len(points_by_position):
        raise ValueError(f"Position {position} has no configured points")
    return points_by_position[position - 1]


def extract_team_tag(player_name, team_tags=TEAM_TAGS):
    """Extract a team tag when it appears at the start or end of a player name."""

    normalized_player = normalize_text(player_name)
    sorted_tags = sorted(
        team_tags, key=lambda tag: len(normalize_text(tag)), reverse=True
    )

    for team_tag in sorted_tags:
        normalized_tag = normalize_text(team_tag)
        if normalized_player.startswith(normalized_tag):
            return team_tag
        if normalized_player.endswith(normalized_tag):
            return team_tag

    return None


def validate_player_tags(players=PLAYERS, team_tags=TEAM_TAGS):
    """Ensure every configured player has a recognizable team tag."""

    players_without_team = [
        player for player in players if extract_team_tag(player, team_tags) is None
    ]
    if players_without_team:
        raise ValueError(
            "Players without team tag at the start or end: "
            + ", ".join(players_without_team)
        )


def is_bot_name(normalized_name, bot_names=BOT_NAMES):
    """Return whether a normalized OCR reading looks like a playable character."""

    normalized_bot_names = [normalize_text(bot_name) for bot_name in bot_names]
    if normalized_name in normalized_bot_names:
        return True

    shortest_bot_name = min(len(bot_name) for bot_name in normalized_bot_names)
    if len(normalized_name) < shortest_bot_name:
        return False

    match = process.extractOne(
        normalized_name, normalized_bot_names, scorer=fuzz.WRatio
    )
    return match is not None and match[1] >= BOT_MATCH_THRESHOLD


def _normalized_players(players):
    return {normalize_text(player): player for player in players}


def _best_player_match(normalized_name, players, excluded_players):
    normalized_players = {
        normalized: player
        for normalized, player in _normalized_players(players).items()
        if player not in excluded_players
    }
    if not normalized_players:
        return FuzzyMatch("", 0, "unmatched")

    match, score, _ = process.extractOne(
        normalized_name, normalized_players.keys(), scorer=fuzz.WRatio
    )
    return FuzzyMatch(normalized_players[match], score, "players")


def _best_previous_ocr_match(normalized_name, ocr_to_player_names, excluded_players):
    available_ocr_names = {
        ocr_name: player
        for ocr_name, player in ocr_to_player_names.items()
        if player not in excluded_players
    }
    if not available_ocr_names:
        return None

    match, score, _ = process.extractOne(
        normalized_name, available_ocr_names.keys(), scorer=fuzz.WRatio
    )
    return FuzzyMatch(available_ocr_names[match], score, "previous_ocr")


def fuzzy_match(
    normalized_name,
    ocr_to_player_names,
    players=PLAYERS,
    threshold=MATCH_THRESHOLD,
    excluded_players=None,
):
    """Match one normalized OCR reading to the best available player."""

    excluded_players = set(excluded_players or ())
    best_match = _best_player_match(normalized_name, players, excluded_players)

    if best_match.score < threshold:
        previous_ocr_match = _best_previous_ocr_match(
            normalized_name, ocr_to_player_names, excluded_players
        )
        if (
            previous_ocr_match is not None
            and previous_ocr_match.score > best_match.score
        ):
            best_match = previous_ocr_match

    return best_match


def _resolve_unique_matches(normalized_rows, players):
    """Assign player names to rows while preventing duplicate players."""

    assignments = {}
    assigned_players = {}
    excluded_by_row = {row_number: set() for row_number, _ in normalized_rows}
    ocr_to_player_names = {}
    pending_rows = list(normalized_rows)

    while pending_rows:
        row_number, normalized_text = pending_rows.pop(0)
        match = fuzzy_match(
            normalized_text,
            ocr_to_player_names,
            players,
            excluded_players=excluded_by_row[row_number],
        )

        if not match.player_name:
            assignments[row_number] = match
            continue

        current_owner = assigned_players.get(match.player_name)
        if current_owner is None:
            assignments[row_number] = match
            assigned_players[match.player_name] = row_number
            ocr_to_player_names[normalized_text] = match.player_name
            continue

        current_match = assignments[current_owner]
        if current_match.score >= match.score:
            excluded_by_row[row_number].add(match.player_name)
            pending_rows.append((row_number, normalized_text))
            continue

        current_normalized_text = dict(normalized_rows)[current_owner]
        excluded_by_row[current_owner].add(match.player_name)
        assignments[row_number] = match
        assigned_players[match.player_name] = row_number
        pending_rows.append((current_owner, current_normalized_text))

    return assignments


def build_scoreboard_results(ocr_results, players=PLAYERS):
    """Build structured race rows from OCR output.

    Bots are replaced by the missing player and rows absent from OCR are added as
    missing-player rows, so point totals can still be calculated.
    """

    ocr_rows = [
        (row_number, ocr_text, normalize_text(ocr_text))
        for row_number, ocr_text in ocr_results
    ]
    normalized_rows = [
        (row_number, normalized_text)
        for row_number, _, normalized_text in ocr_rows
        if not is_bot_name(normalized_text)
    ]
    assignments = _resolve_unique_matches(normalized_rows, players)
    used_players = {
        match.player_name for match in assignments.values() if match.player_name
    }
    missing_players = [player for player in players if player not in used_players]

    scoreboard_rows = []
    for row_number, ocr_text, normalized_text in ocr_rows:
        row_points = points_for_position(row_number)
        if is_bot_name(normalized_text):
            points_recipient = missing_players.pop(0) if missing_players else ""
            scoreboard_rows.append(
                ScoreboardRowResult(
                    row_number=row_number,
                    points=row_points,
                    ocr_text=ocr_text,
                    normalized_text=normalized_text,
                    matched_player=points_recipient,
                    points_recipient=points_recipient,
                    match_score=100,
                    match_source="bot_replacement",
                    is_bot=True,
                )
            )
            continue

        match = assignments[row_number]
        scoreboard_rows.append(
            ScoreboardRowResult(
                row_number=row_number,
                points=row_points,
                ocr_text=ocr_text,
                normalized_text=normalized_text,
                matched_player=match.player_name,
                points_recipient=match.player_name,
                match_score=match.score,
                match_source=match.source,
            )
        )

    used_positions = {row_number for row_number, _, _ in ocr_rows}
    missing_positions = [
        position
        for position in range(1, len(POINTS_BY_POSITION) + 1)
        if position not in used_positions
    ]
    for position, player in zip(missing_positions, missing_players):
        scoreboard_rows.append(
            ScoreboardRowResult(
                row_number=position,
                points=points_for_position(position),
                ocr_text="",
                normalized_text="",
                matched_player=player,
                points_recipient=player,
                match_score=0,
                match_source="missing_player",
                is_missing_player=True,
            )
        )

    return sorted(scoreboard_rows, key=lambda row: row.row_number)


def build_player_points(scoreboard_rows):
    """Sum race points by player."""

    points_by_player = {}
    for row in scoreboard_rows:
        if not row.points_recipient:
            continue
        points_by_player[row.points_recipient] = (
            points_by_player.get(row.points_recipient, 0) + row.points
        )
    return points_by_player


def build_team_points(scoreboard_rows, team_tags=TEAM_TAGS):
    """Sum race points by team tag."""

    points_by_team = {}
    for row in scoreboard_rows:
        if not row.points_recipient:
            continue

        team_tag = extract_team_tag(row.points_recipient, team_tags)
        if team_tag is None:
            raise ValueError(f"Could not find team tag for {row.points_recipient}")

        points_by_team[team_tag] = points_by_team.get(team_tag, 0) + row.points

    return points_by_team


def build_net_points(team_points):
    """Compute net points per team vs the best other team.

    For a 1v1 (e.g., RK 42 vs ne 40), the result is RK +2 and ne -2.
    With more teams, each team's net is its points minus the best
    points scored by any other team in the race.

    Args:
        team_points: Dict mapping team tag to race points.

    Returns:
        Dict mapping team tag to net points.
    """
    if len(team_points) < 2:
        return {team: 0 for team in team_points}

    best_other = {
        team: max(p for other, p in team_points.items() if other != team)
        for team in team_points
    }
    return {team: pts - best_other[team] for team, pts in team_points.items()}


def add_race_to_standings(
    scoreboard_rows,
    standings=None,
    players=PLAYERS,
    team_tags=TEAM_TAGS,
):
    """Add one race result to cumulative war standings."""

    validate_player_tags(players, team_tags)

    if standings is None:
        standings = WarStandings()

    for player, points in build_player_points(scoreboard_rows).items():
        standings.player_points[player] = (
            standings.player_points.get(player, 0) + points
        )

    for team, points in build_team_points(scoreboard_rows, team_tags).items():
        standings.team_points[team] = standings.team_points.get(team, 0) + points

    standings.races_played += 1
    return standings
