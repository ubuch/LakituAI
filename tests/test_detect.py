import unittest
from pathlib import Path

import cv2
import numpy as np

from lakituai import detect

TMP = Path(__file__).resolve().parents[1] / "tmp"


def blank_frame(height=1080, width=1920, color=(20, 20, 20)):
    """A plain dark frame with no scoreboard."""

    return np.full((height, width, 3), color, dtype=np.uint8)


def _texture(shape, seed=0, density=0.15):
    """Boolean mask of white "text" speckles used to give a panel row edges."""
    rng = np.random.default_rng(seed)
    return rng.random(shape) < density


def frame_with_panel(bgr=(40, 60, 200), height=1080, width=1920):
    """Frame whose panel zone is a textured saturated block.

    Models a fully-appeared scoreboard: a contiguous saturated block with
    text-like content in every row (so the edge check passes too).
    """

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    frame[y1:y2, x1:x2] = bgr
    zone = frame[y1:y2, x1:x2]
    zone[_texture(zone.shape[:2])] = 240
    return frame


def frame_with_falling_panel(bgr=(40, 60, 200), height=1080, width=1920, fill=0.85):
    """Frame whose panel zone is mostly filled from the top (mid-animation).

    The block already covers most of the zone (as in the real a_medias3
    sample, which reached ~91%), so the gate fires; the bottom rows have not
    landed, so the complete-panel check must defer capture.
    """

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    bottom = y1 + int((y2 - y1) * fill)
    frame[y1:bottom, x1:x2] = bgr
    zone = frame[y1:bottom, x1:x2]
    zone[_texture(zone.shape[:2])] = 240
    return frame


def frame_with_backdrop_only(bgr=(40, 60, 200), height=1080, width=1920):
    """Smooth saturated block with NO content (mid-appearance).

    Models the premature capture seen on the Windows test video: the panel's
    colored backdrop already covers the whole zone (saturation passes) but the
    rows have not been drawn yet (no edges).
    """

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    frame[y1:y2, x1:x2] = bgr
    return frame


def frame_with_scattered_color(height=1080, width=1920, blobs=40):
    """Frame with many small saturated patches spread over the zone.

    Models gameplay on a colorful track (largest blob << zone area).
    """

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    rng = np.random.default_rng(0)
    for _ in range(blobs):
        by = rng.integers(y1, y2 - 30)
        bx = rng.integers(x1, x2 - 30)
        frame[by : by + 20, bx : bx + 20] = (rng.integers(120, 255), 30, 30)
    return frame


class DetectZoneTests(unittest.TestCase):
    def test_zone_rect_scales_with_resolution(self):
        for (h, w) in [(1080, 1920), (1440, 2560), (720, 1280)]:
            y1, y2, x1, x2 = detect.zone_rect((h, w, 3))
            self.assertAlmostEqual((x2 - x1) / w, detect.ZONE_X2 - detect.ZONE_X1, places=3)
            self.assertAlmostEqual((y2 - y1) / h, detect.ZONE_Y2 - detect.ZONE_Y1, places=3)

    def test_crop_zone_returns_panel_region(self):
        frame = blank_frame()
        y1, y2, x1, x2 = detect.zone_rect(frame.shape)
        zone = detect.crop_zone(frame)
        self.assertEqual(zone.shape[:2], (y2 - y1, x2 - x1))


class GateTests(unittest.TestCase):
    def test_full_panel_is_scoreboard(self):
        for color in [(40, 60, 200), (30, 200, 30), (10, 210, 210), (200, 200, 20)]:
            with self.subTest(color=color):
                zone = detect.crop_zone(frame_with_panel(color))
                self.assertGreaterEqual(detect.largest_cc_fraction(zone), 0.90)
                self.assertTrue(detect.is_scoreboard(zone))

    def test_scattered_color_is_not_scoreboard(self):
        zone = detect.crop_zone(frame_with_scattered_color())
        frac = detect.largest_cc_fraction(zone)
        self.assertLess(frac, 0.40)
        self.assertFalse(detect.is_scoreboard(zone))

    def test_blank_frame_is_not_scoreboard(self):
        zone = detect.crop_zone(blank_frame())
        self.assertAlmostEqual(detect.largest_cc_fraction(zone), 0.0)
        self.assertFalse(detect.is_scoreboard(zone))

    def test_falling_panel_triggers_gate_but_not_complete(self):
        # A mostly-down panel is still a big contiguous blob (>= 60%), so the
        # gate fires while the panel is still animating -- but the bottom
        # bands are still empty, so the complete-panel check must reject it.
        zone = detect.crop_zone(frame_with_falling_panel())
        self.assertGreaterEqual(detect.largest_cc_fraction(zone), detect.DEFAULT_GATE_FRACTION)
        self.assertFalse(detect.is_scoreboard(zone))

    def test_backdrop_only_panel_is_not_complete(self):
        # The premature state from the Windows test video: the colored bars
        # already cover the whole zone (gate + saturation pass) but there is
        # no content -- the edge check must reject it.
        zone = detect.crop_zone(frame_with_backdrop_only())
        self.assertGreaterEqual(detect.largest_cc_fraction(zone), detect.DEFAULT_GATE_FRACTION)
        self.assertGreaterEqual(detect.band_coverage(zone).min(), detect.DEFAULT_COMPLETE_MIN_BAND)
        self.assertLess(detect.edge_band_coverage(zone).min(), detect.DEFAULT_COMPLETE_MIN_EDGE)
        self.assertFalse(detect.is_scoreboard(zone))


class BandCoverageTests(unittest.TestCase):
    def test_complete_panel_has_every_band_saturated_and_textured(self):
        for color in [(40, 60, 200), (30, 200, 30), (200, 200, 20)]:
            with self.subTest(color=color):
                zone = detect.crop_zone(frame_with_panel(color))
                coverage = detect.band_coverage(zone)
                edges = detect.edge_band_coverage(zone)
                self.assertEqual(len(coverage), detect.BAND_COUNT)
                self.assertEqual(len(edges), detect.BAND_COUNT)
                self.assertGreaterEqual(coverage.min(), detect.DEFAULT_COMPLETE_MIN_BAND)
                self.assertGreaterEqual(edges.min(), detect.DEFAULT_COMPLETE_MIN_EDGE)
                self.assertTrue(detect.is_complete_panel(zone))

    def test_falling_panel_has_empty_bottom_bands(self):
        zone = detect.crop_zone(frame_with_falling_panel(fill=0.85))
        coverage = detect.band_coverage(zone)
        self.assertGreaterEqual(coverage[0], detect.DEFAULT_COMPLETE_MIN_BAND)
        self.assertLess(coverage[-1], detect.DEFAULT_COMPLETE_MIN_BAND)
        self.assertFalse(detect.is_complete_panel(zone))

    def test_blank_zone_is_not_complete(self):
        self.assertFalse(detect.is_complete_panel(detect.crop_zone(blank_frame())))


class RealSamplesTests(unittest.TestCase):
    """Validate against the real captures in tmp/ (skipped if absent)."""

    def _load(self, name):
        path = TMP / name
        if not path.exists():
            self.skipTest(f"missing sample {name}")
        return cv2.imread(str(path))

    def test_gameplay_samples_are_not_scoreboards(self):
        for name in ("carrera1.png", "carrera2.png", "carrera3.png"):
            img = self._load(name)
            zone = detect.crop_zone(img)
            self.assertLess(detect.largest_cc_fraction(zone), detect.DEFAULT_GATE_FRACTION, msg=name)
            self.assertFalse(detect.is_scoreboard(zone), msg=name)

    def test_incomplete_scoreboard_samples_are_not_scoreboards(self):
        # The "a medias" panel is ~91% present (gate passes) but its bottom
        # rows are missing; the premature capture from the Windows video has
        # full saturation but no content (no edges). Both must be rejected.
        for name in ("scoreboard_a_medias3.png", "foto_daemon1.jpg"):
            img = self._load(name)
            zone = detect.crop_zone(img)
            self.assertGreaterEqual(
                detect.largest_cc_fraction(zone), detect.DEFAULT_GATE_FRACTION, msg=name
            )
            self.assertFalse(detect.is_scoreboard(zone), msg=name)

    def test_complete_scoreboard_samples_are_scoreboards(self):
        for name in (
            "scoreboard_completo_con_equipos1.png",
            "scoreboard_completo_con_equipos2.png",
            "test_daemon1.png",
        ):
            img = self._load(name)
            zone = detect.crop_zone(img)
            self.assertGreaterEqual(
                detect.band_coverage(zone).min(), detect.DEFAULT_COMPLETE_MIN_BAND, msg=name
            )
            self.assertGreaterEqual(
                detect.edge_band_coverage(zone).min(), detect.DEFAULT_COMPLETE_MIN_EDGE, msg=name
            )
            self.assertTrue(detect.is_scoreboard(zone), msg=name)


if __name__ == "__main__":
    unittest.main()
