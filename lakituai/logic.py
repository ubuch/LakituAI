from dataclasses import dataclass
from pathlib import Path

import cv2
from rapidfuzz import process, fuzz

BASE_W = 1920
BASE_H = 1080
NUMBER_OF_ROWS = 12
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_DIR = PROJECT_ROOT / "resources"
SCREENSHOTS_DIR = RESOURCES_DIR / "screenshots"
ROWS_DIR = RESOURCES_DIR / "rows"
MATCH_THRESHOLD = 70
POINTS_BY_POSITION = (15, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)

PLAYERS = [
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
]


@dataclass(frozen=True)
class FuzzyMatch:
    player_name: str
    score: float
    source: str


@dataclass(frozen=True)
class ScoreboardRowResult:
    row_number: int
    points: int
    ocr_text: str
    normalized_text: str
    matched_player: str
    match_score: float
    match_source: str


def _get_image(path):
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return img


def _save_img(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def upscale_img(path):
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
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def cut_scoreboard_rows(img, output_dir=ROWS_DIR, number_of_rows=NUMBER_OF_ROWS):
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
    image = upscale_img(screenshot_path)
    image_gray = convert_to_grayscale(image)
    return cut_scoreboard_rows(image_gray, output_dir)


def normalize_text(text):
    return text.lower().replace(".", "").replace(" ", "")


def points_for_position(position, points_by_position=POINTS_BY_POSITION):
    if position < 1 or position > len(points_by_position):
        raise ValueError(f"Position {position} has no configured points")
    return points_by_position[position - 1]


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
    excluded_players = set(excluded_players or ())
    best_match = _best_player_match(normalized_name, players, excluded_players)

    if best_match.score < threshold:
        previous_ocr_match = _best_previous_ocr_match(
            normalized_name, ocr_to_player_names, excluded_players
        )
        if previous_ocr_match is not None and previous_ocr_match.score > best_match.score:
            best_match = previous_ocr_match

    return best_match


def _resolve_unique_matches(normalized_rows, players):
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
    ocr_rows = [
        (row_number, ocr_text, normalize_text(ocr_text))
        for row_number, ocr_text in ocr_results
    ]
    normalized_rows = [
        (row_number, normalized_text)
        for row_number, _, normalized_text in ocr_rows
    ]
    assignments = _resolve_unique_matches(normalized_rows, players)

    return [
        ScoreboardRowResult(
            row_number=row_number,
            points=points_for_position(row_number),
            ocr_text=ocr_text,
            normalized_text=normalized_text,
            matched_player=assignments[row_number].player_name,
            match_score=assignments[row_number].score,
            match_source=assignments[row_number].source,
        )
        for row_number, ocr_text, normalized_text in ocr_rows
    ]
