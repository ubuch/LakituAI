"""Command-line entry point for processing Mario Kart World scoreboard screenshots.

This module provides the main CLI interface for processing race scoreboards and
calculating player/team points.
"""

import argparse
import sys
from pathlib import Path

from lakituai import logic, ocr


def parse_arguments() -> argparse.Namespace:
    """Parse and return command-line arguments.
    
    Returns:
        Parsed arguments with 'image_path' attribute.
    
    Raises:
        SystemExit: If required arguments are missing or invalid.
    """
    parser = argparse.ArgumentParser(
        description="Process a Mario Kart World scoreboard screenshot and calculate points.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m lakituai path/to/screenshot.jpg\n"
            "  python -m lakituai /home/user/races/race1.png"
        ),
    )
    
    parser.add_argument(
        "image_path",
        type=str,
        help="Path to the scoreboard screenshot image (JPEG, PNG, etc.)",
    )
    
    return parser.parse_args()


def validate_image_path(image_path: str) -> Path:
    """Validate that the image path exists and is a file.
    
    Args:
        image_path: String path to the image file.
    
    Returns:
        Validated Path object.
    
    Raises:
        FileNotFoundError: If file doesn't exist or is a directory.
        ValueError: If file extension is not a common image format.
    """
    path = Path(image_path).resolve()
    
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    
    if not path.is_file():
        raise ValueError(f"Path is not a file: {image_path}")
    
    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
    if path.suffix.lower() not in valid_extensions:
        raise ValueError(
            f"Unsupported image format: {path.suffix}. "
            f"Supported formats: {', '.join(valid_extensions)}"
        )
    
    return path


def process_scoreboard(image_path: Path) -> None:
    """Process a scoreboard image and print results.
    
    Extracts scoreboard rows from image, runs OCR, matches players, and
    calculates race points. Results are printed to stdout.
    
    Args:
        image_path: Path to the scoreboard image.
    
    Raises:
        FileNotFoundError: If image cannot be read.
        ValueError: If OCR or processing fails.
    """
    print(f"Processing image: {image_path}")
    print("-" * 80)
    
    try:
        row_paths = logic.prepare_scoreboard_rows(image_path)
        print(f"Extracted {len(row_paths)} scoreboard rows")
        
        processor, model = ocr.init_ocr()
        ocr_results = ocr.run_ocr(processor, model, row_paths)
        scoreboard_rows = logic.build_scoreboard_results(ocr_results)
        
        print("\nSCOREBOARD RESULTS:")
        print("-" * 80)
        for row in scoreboard_rows:
            row_type = "BOT" if row.is_bot else "MISSING" if row.is_missing_player else "PLAYER"
            print(
                f"ROW {row.row_number:2d} [{row_type:7s}]: {row.ocr_text:20s} -> "
                f"{row.normalized_text:20s} -> {row.matched_player:15s} || "
                f"POINTS: {row.points:2d} TO: {row.points_recipient:15s} || "
                f"MATCH: {row.match_score:5.1f} ({row.match_source})"
            )
        
        standings = logic.add_race_to_standings(scoreboard_rows)
        
        print("\n" + "=" * 80)
        print("TOURNAMENT STANDINGS")
        print("=" * 80)
        print("\nPLAYER POINTS:")
        for player in sorted(standings.player_points, key=standings.player_points.get, reverse=True):
            print(f"  {player:20s}: {standings.player_points[player]:3d}")
        
        print("\nTEAM POINTS:")
        for team in sorted(standings.team_points, key=standings.team_points.get, reverse=True):
            print(f"  {team:20s}: {standings.team_points[team]:3d}")
        
        print(f"\nRaces played: {standings.races_played}")
        
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"ERROR processing image: {e}", file=sys.stderr)
        raise


def main() -> None:
    """Main CLI entry point."""
    try:
        args = parse_arguments()
        image_path = validate_image_path(args.image_path)
        process_scoreboard(image_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
