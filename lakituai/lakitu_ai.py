from lakituai import logic, ocr


def main():
    path = logic.SCREENSHOTS_DIR / "screenshot1.jpg"
    row_paths = logic.prepare_scoreboard_rows(path)

    processor, model = ocr.init_ocr()
    ocr_results = ocr.run_ocr(processor, model, row_paths)
    scoreboard_rows = logic.build_scoreboard_results(ocr_results)

    for row in scoreboard_rows:
        print(
            f"ROW {row.row_number}: {row.ocr_text} -> {row.normalized_text} -> "
            f"{row.matched_player} || POINTS: {row.points} || "
            f"MATCH: {row.match_score} ({row.match_source})"
        )


if __name__ == "__main__":
    main()
