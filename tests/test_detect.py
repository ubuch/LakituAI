import unittest
from pathlib import Path

import cv2
import numpy as np

from lakituai import detect

TMP = Path(__file__).resolve().parents[1] / "tmp"


def blank_frame(height=1080, width=1920, color=(20, 20, 20)):
    """A plain dark frame with no scoreboard."""

    return np.full((height, width, 3), color, dtype=np.uint8)


def frame_with_panel(bgr=(40, 60, 200), height=1080, width=1920):
    """Frame whose panel zone is filled with one solid saturated color.

    Models a fully-appeared scoreboard (a contiguous saturated block).
    """

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    frame[y1:y2, x1:x2] = bgr
    return frame


def frame_with_falling_panel(bgr=(40, 60, 200), height=1080, width=1920, fill=0.85):
    """Frame whose panel zone is mostly filled from the top (mid-animation).

    The block already covers most of the zone (as in the real a_medias3
    sample, which reached ~91%), so the gate fires; it is the *stability*
    check that must defer capture until the fall animation settles.
    """

    frame = blank_frame(height, width)
    y1, y2, x1, x2 = detect.zone_rect(frame.shape)
    bottom = y1 + int((y2 - y1) * fill)
    frame[y1:bottom, x1:x2] = bgr
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

    def test_falling_panel_triggers_gate_like_a_medias_sample(self):
        # A mostly-down panel is still a big contiguous blob (>= 60%), so the
        # gate fires while the panel is still animating -- stability is what
        # defers capture until the fall settles.
        zone = detect.crop_zone(frame_with_falling_panel())
        self.assertGreaterEqual(detect.largest_cc_fraction(zone), detect.DEFAULT_GATE_FRACTION)


class SignatureTests(unittest.TestCase):
    def test_identical_frames_have_zero_diff(self):
        a = detect.zone_signature(detect.crop_zone(blank_frame()))
        self.assertAlmostEqual(detect.signature_diff(a, a), 0.0)

    def test_different_zones_have_positive_diff(self):
        a = detect.zone_signature(detect.crop_zone(blank_frame()))
        b = detect.zone_signature(detect.crop_zone(frame_with_panel()))
        self.assertGreater(detect.signature_diff(a, b), 0.0)

    def test_signature_diff_tolerates_different_sizes(self):
        a = detect.zone_signature(detect.crop_zone(blank_frame(1080, 1920)))
        b = detect.zone_signature(detect.crop_zone(blank_frame(720, 1280)))
        self.assertGreaterEqual(detect.signature_diff(a, b), 0.0)


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
            frac = detect.largest_cc_fraction(detect.crop_zone(img))
            self.assertLess(frac, detect.DEFAULT_GATE_FRACTION, msg=name)

    def test_scoreboard_samples_are_scoreboards(self):
        for name in (
            "scoreboard_a_medias3.png",
            "scoreboard_completo_con_equipos1.png",
            "scoreboard_completo_con_equipos2.png",
        ):
            img = self._load(name)
            frac = detect.largest_cc_fraction(detect.crop_zone(img))
            self.assertGreaterEqual(frac, detect.DEFAULT_GATE_FRACTION, msg=name)

    def test_complete_scoreboard_is_stable_across_noised_frames(self):
        # Stability compares the SAME scoreboard across consecutive polls, so a
        # scoreboard frame should differ only slightly from a lightly-noised copy
        # (mimicking capture noise), well under the stability epsilon.
        img = self._load("scoreboard_completo_con_equipos1.png")
        base = detect.zone_signature(detect.crop_zone(img))
        noisy = np.clip(base + np.random.default_rng(1).integers(-3, 4, base.shape), 0, 255).astype(
            np.float32
        )
        self.assertLess(detect.signature_diff(base, noisy), detect.DEFAULT_STABILITY_EPS)


if __name__ == "__main__":
    unittest.main()
