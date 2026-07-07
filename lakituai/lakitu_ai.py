"""Command-line entry point for processing the sample scoreboard screenshot."""

from lakituai import logic, ocr


def main():
    """Run the current single-image OCR and scoring pipeline."""

    path = logic.SCREENSHOTS_DIR / "screenshot1.jpg"
    row_paths = logic.prepare_scoreboard_rows(path)

    processor, model = ocr.init_ocr()
    ocr_results = ocr.run_ocr(processor, model, row_paths)
    scoreboard_rows = logic.build_scoreboard_results(ocr_results)

    for row in scoreboard_rows:
        row_type = "BOT" if row.is_bot else "MISSING" if row.is_missing_player else "PLAYER"
        print(
            f"ROW {row.row_number} [{row_type}]: {row.ocr_text} -> "
            f"{row.normalized_text} -> {row.matched_player} || "
            f"POINTS: {row.points} TO: {row.points_recipient} || "
            f"MATCH: {row.match_score} ({row.match_source})"
        )

    standings = logic.add_race_to_standings(scoreboard_rows)
    print(f"PLAYER POINTS: {standings.player_points}")
    print(f"TEAM POINTS: {standings.team_points}")


if __name__ == "__main__":
    main()
