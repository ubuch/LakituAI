"""Screen-detection helpers for the LakituAI background daemon.

The daemon watches the screen and must decide two things cheaply, every poll
(~0.5s), without loading the OCR model:

1. **Is a scoreboard visible?**  Heuristic: the Mario Kart World results panel
   is a large, *contiguous* block of saturated color that fills most of its
   on-screen region.  Plain gameplay, even on colorful tracks, only produces
   scattered saturated patches (the largest of which covers far less area).

2. **Is it done appearing?**  The panel "falls in" top-to-bottom; while it is
   animating the frame content keeps changing.  We therefore require the panel
   region to be *stable* (near-identical between consecutive polls) before we
   save the screenshot.

Both checks are resolution-independent: every coordinate is expressed as a
fraction of the frame size, matching the proportional crop already used by
``lakituai.logic.upscale_img``.

Calibration (against real samples in ``tmp/``): the scoreboard's largest
connected saturated region covered 91-100% of the panel zone, while gameplay
peaked at ~39%.  The gate threshold lives comfortably in that gap.
"""

from __future__ import annotations

import cv2
import numpy as np

# Panel zone as a fraction of the frame, identical to logic.upscale_img.
# x: 1269-1664 of 1920, y: 43-956 of 1080.
ZONE_X1, ZONE_X2 = 1269 / 1920, 1664 / 1920
ZONE_Y1, ZONE_Y2 = 43 / 1080, 956 / 1080

# Defaults; the daemon overrides these from config.
DEFAULT_GATE_FRACTION = 0.60  # largest saturated blob must cover >= 60% of zone
DEFAULT_STABILITY_EPS = 4.0  # mean abs diff between consecutive zone signatures
DEFAULT_STABILITY_FRAMES = 3  # ...held for this many consecutive samples
_SATURATION = 0.45
_VALUE = 110
_CLOSE_ITER = 3
_CLOSE_KERNEL = (5, 5)
_SIG_SIZE = (32, 64)  # downscaled grayscale signature of the zone


def zone_rect(frame_shape) -> tuple[int, int, int, int]:
    """Return (y1, y2, x1, x2) pixel bounds of the panel zone for a frame.

    Args:
        frame_shape: (height, width) or (height, width, channels).

    Returns:
        Tuple (y1, y2, x1, x2) in pixel coordinates.
    """

    height, width = frame_shape[:2]
    x1 = int(ZONE_X1 * width)
    x2 = int(ZONE_X2 * width)
    y1 = int(ZONE_Y1 * height)
    y2 = int(ZONE_Y2 * height)
    return y1, y2, x1, x2


def crop_zone(frame: np.ndarray) -> np.ndarray:
    """Crop the panel zone out of a BGR or grayscale frame."""

    y1, y2, x1, x2 = zone_rect(frame.shape)
    return frame[y1:y2, x1:x2]


def saturated_mask(zone_bgr: np.ndarray) -> np.ndarray:
    """Return a uint8 (0/255) mask of saturated, bright pixels in a BGR zone.

    The mask is color-agnostic: it is true wherever the pixel is both bright
    (high value) and colorful (high HSV saturation), so it fires for red, blue,
    yellow or green team panels alike.
    """

    bgr = zone_bgr.astype(np.float32)
    b, g, r = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    with np.errstate(divide="ignore", invalid="ignore"):
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
    return ((sat > _SATURATION) & (mx > _VALUE)).astype(np.uint8) * 255


def largest_cc_fraction(zone_bgr: np.ndarray) -> float:
    """Fraction (0-1) of the zone covered by the largest connected saturated blob.

    Closing first bridges the small gaps between rows so a filled panel
    registers as one giant component even though individual rows are separate
    colored bands.

    Args:
        zone_bgr: BGR crop of the panel zone.

    Returns:
        Area of the largest connected component as a fraction of the zone.
        Returns 0.0 when no saturated pixels are present.
    """

    mask = saturated_mask(zone_bgr)
    if mask.sum() == 0:
        return 0.0

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, _CLOSE_KERNEL)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=_CLOSE_ITER)

    n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        closed, connectivity=8
    )
    if n <= 1:
        return 0.0

    largest = max(stats[1:, cv2.CC_STAT_AREA])
    total = closed.shape[0] * closed.shape[1]
    return float(largest) / float(total)


def zone_signature(zone_gray: np.ndarray) -> np.ndarray:
    """Return a small fixed-size grayscale signature of a zone for diffing."""

    return cv2.resize(zone_gray, _SIG_SIZE, interpolation=cv2.INTER_AREA).astype(
        np.float32
    )


def signature_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference between two zone signatures (0 = identical)."""

    if a.shape != b.shape:
        b = cv2.resize(b, a.shape[::-1], interpolation=cv2.INTER_AREA).astype(
            np.float32
        )
    return float(np.abs(a - b).mean())


def is_scoreboard(zone_bgr: np.ndarray, gate_fraction: float = DEFAULT_GATE_FRACTION) -> bool:
    """Cheap test for "a scoreboard is on screen".

    True when the largest contiguous saturated region covers at least
    ``gate_fraction`` of the panel zone.
    """

    return largest_cc_fraction(zone_bgr) >= gate_fraction
