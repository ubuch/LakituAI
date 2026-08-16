"""Screen-detection helpers for the LakituAI background daemon.

The daemon watches the screen and must decide cheaply, every poll (~0.5s),
without loading the OCR model, whether a *fully-appeared* scoreboard is on
screen. The panel is detected on a **single frame** (no motion heuristics, so
it keeps working on live video where the panel shows subtle animation):

1. **Is a scoreboard visible?**  Heuristic: the Mario Kart World results panel
   is a large, *contiguous* block of saturated color that covers most of its
   on-screen region (the gate).  Plain gameplay, even on colorful tracks, only
   produces scattered saturated patches (largest covers far less area).

2. **Is it complete (settled)?**  Two sub-checks, both resolution-independent
   per horizontal band of the zone:
   - ``band_coverage``: every band must be substantially *saturated*.  This
     rejects a panel still falling in, whose rows have not arrived yet (a
     partially appeared panel has empty bottom bands).
   - ``edge_band_coverage``: every band must have real *content* (edges from
     the player rows / numbers / portraits).  This rejects the mid-appearance
     state where the panel's colored backdrop already covers the whole zone
     but the rows have not been drawn yet (seen once on the Windows test
     video: every band was saturated, but the row content was still missing).

The defaults below are derived from real captures: a settled scoreboard
measures ~85-91% minimum band saturation and ~2.2-3.4 minimum edge density
(out of 100); gameplay peaks at ~39% covered area; a partially appeared
panel drops to ~32% saturation with no content, and a premature backdrop
capture has full saturation but no edges.
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
DEFAULT_COMPLETE_MIN_BAND = 0.50  # every band must be >= this saturated (0-1)
DEFAULT_COMPLETE_MIN_EDGE = 1.5  # every band must have >= this edge density (0-100)
BAND_COUNT = 12  # panel rows (Mario Kart World: 12 slots)
_SATURATION = 0.45
_VALUE = 110
_CLOSE_ITER = 3
_CLOSE_KERNEL = (5, 5)
_EDGE_LOW = 60
_EDGE_HIGH = 160


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


def band_coverage(zone_bgr: np.ndarray, bands: int = BAND_COUNT) -> np.ndarray:
    """Per-band fraction (0-1) of saturated pixels, top to bottom.

    Splits the zone into ``bands`` horizontal strips and reports how much of
    each strip is saturated.  A fully-appeared scoreboard scores high in every
    band; a panel that is still falling in (or stuck half-appeared) has empty
    strips where the rows have not arrived yet.
    """

    mask = saturated_mask(zone_bgr).astype(bool)
    height = mask.shape[0]
    coverage = np.empty(bands, dtype=float)
    for i in range(bands):
        band = mask[int(i * height / bands) : int((i + 1) * height / bands)]
        coverage[i] = float(band.mean())
    return coverage


def edge_band_coverage(zone_bgr: np.ndarray, bands: int = BAND_COUNT) -> np.ndarray:
    """Per-band density (0-100) of edge pixels, top to bottom.

    Edges come from the scoreboard's content (numbers, names, portraits), so
    a band with content has a high value and a smooth colored backdrop has
    ~0.  This catches the mid-appearance state where the panel's colored bars
    already cover the whole zone but the rows have not been drawn yet.
    """

    gray = cv2.cvtColor(zone_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, _EDGE_LOW, _EDGE_HIGH).astype(bool)
    height = edges.shape[0]
    density = np.empty(bands, dtype=float)
    for i in range(bands):
        band = edges[int(i * height / bands) : int((i + 1) * height / bands)]
        density[i] = float(band.mean()) * 100.0
    return density


def is_complete_panel(
    zone_bgr: np.ndarray,
    min_band: float = DEFAULT_COMPLETE_MIN_BAND,
    min_edge: float = DEFAULT_COMPLETE_MIN_EDGE,
) -> bool:
    """True when every band of the zone is saturated *and* has content.

    This is the "settled" check: it accepts a panel as soon as all its rows
    are visibly present (so it fires on the very first frame of a settled
    scoreboard, even on live video) and rejects both partial states we have
    seen in the wild: rows that have not landed yet (empty bottom bands) and
    rows whose content has not been drawn yet (saturated backdrop, no edges).
    """

    return (
        float(band_coverage(zone_bgr).min()) >= min_band
        and float(edge_band_coverage(zone_bgr).min()) >= min_edge
    )


def is_scoreboard(
    zone_bgr: np.ndarray,
    gate_fraction: float = DEFAULT_GATE_FRACTION,
    complete_min_band: float = DEFAULT_COMPLETE_MIN_BAND,
    complete_min_edge: float = DEFAULT_COMPLETE_MIN_EDGE,
) -> bool:
    """Cheap single-frame test for "a complete scoreboard is on screen".

    True when a contiguous saturated blob covers at least ``gate_fraction`` of
    the zone (a scoreboard is present, not gameplay) **and** every horizontal
    band is at least ``complete_min_band`` saturated and has at least
    ``complete_min_edge`` edge density (the panel has fully appeared).
    """

    return largest_cc_fraction(zone_bgr) >= gate_fraction and is_complete_panel(
        zone_bgr, min_band=complete_min_band, min_edge=complete_min_edge
    )
