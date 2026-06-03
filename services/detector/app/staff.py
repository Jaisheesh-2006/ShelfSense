"""Staff classification by dark-uniform appearance (Slice 2.4b, ADR-0009).

Brigade store staff wear a **complete black uniform** (shirt + trousers); the two genuine customers
in the clip wear grey and violet. So "is this person dressed head-to-toe in dark clothing?" is a
strong, cheap discriminator — far better than the earlier presence-time heuristic (ADR-0008/2.4),
which mislabels any shopper who lingers. We reuse the very crop the Re-ID signature samples; only
the measurement differs.

As with reid.py, pixel extraction (`uniform_darkness`, needs OpenCV) is split from the pure
decision logic (`dark_fraction`, `StaffClassifier`) so the policy is unit-testable without a model.

We require **both** the upper and lower body to be dark (not just a dark top) — taking the *min* of
the two halves — so a customer with a dark jacket over light jeans is not misflagged. We also sample
the central column of the box to limit dilution from the (light wood) floor behind the person.

Honest limitation (DESIGN Assumptions): on dark evening footage a customer in genuinely black
clothing would be misflagged. We tune the threshold against ground truth and report the measured
separation between staff and customers rather than claim precision.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# HSV Value (0-255) at or below which a pixel counts as "dark"/near-black. Surfaced as config.
DARK_V_MAX = 70
# Fraction of the box width kept (central column) when measuring darkness, to limit background.
CENTRAL_COLUMN = 0.6


@dataclass
class ColorHeuristic:
    hsv_lower: tuple[int, int, int]
    hsv_upper: tuple[int, int, int]
    body_part: str  # "upper", "lower", "both"

# Pluggable color registry
COLOR_HEURISTICS = {
    "black": ColorHeuristic((0, 0, 0), (179, 255, 70), "both"), # v_max will override 70
    "pink": ColorHeuristic((140, 50, 50), (170, 255, 255), "upper")
}


def color_fraction(
    hsv: np.ndarray,
    lower: tuple[int, int, int],
    upper: tuple[int, int, int],
) -> float:
    """Fraction of pixels whose HSV values fall within the bounds."""
    if hsv.size == 0:
        return 0.0
    import cv2
    mask = cv2.inRange(
        hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8),
    )
    return float(np.count_nonzero(mask) / (hsv.shape[0] * hsv.shape[1]))


def measure_uniform_color(
    image: np.ndarray, x: int, y: int, w: int, h: int, color_name: str | None, v_max: int = 70
) -> float:
    """Color-uniform score in [0,1] for a person box, based on the heuristic color."""
    if not color_name:
        return 0.0
        
    heuristic = COLOR_HEURISTICS.get(color_name.lower())
    if not heuristic:
        return 0.0

    import cv2

    height, width = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = image[y0:y1, x0:x1]
    
    # Keep the central column where the body is, trimming side background (floor/shelves).
    cw = crop.shape[1]
    margin = int(cw * (1.0 - CENTRAL_COLUMN) / 2.0)
    if cw - 2 * margin >= 1:
        crop = crop[:, margin : cw - margin]
        
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    
    lower = heuristic.hsv_lower
    upper = heuristic.hsv_upper
    
    # Dynamic v_max override for "black" to support the settings config
    if color_name.lower() == "black":
        upper = (179, 255, v_max)
        
    mid = hsv.shape[0] // 2
    if mid < 1:
        return color_fraction(hsv, lower, upper)
        
    upper_frac = color_fraction(hsv[:mid], lower, upper)
    lower_frac = color_fraction(hsv[mid:], lower, upper)
    
    if heuristic.body_part == "upper":
        return upper_frac
    elif heuristic.body_part == "lower":
        return lower_frac
    else:
        return min(upper_frac, lower_frac)


@dataclass
class _TrackColorScore:
    total: float
    count: int


class StaffClassifier:
    """Accumulates per-frame color-uniform scores per track, then decides `is_staff` by threshold.

    Pure given the scores (callers pass numbers, not pixels), so the policy is fully unit-testable.
    A track is staff if its mean color score >= `threshold`. An optional presence fallback (off by
    default) also flags a track present beyond `presence_fallback_ms` even if not scoring high.
    """

    def __init__(self, threshold: float, presence_fallback_ms: int | None = None) -> None:
        self.threshold = threshold
        self.presence_fallback_ms = presence_fallback_ms
        self._tracks: dict[tuple[str, int], _TrackColorScore] = {}

    def observe(self, camera_id: str, track_id: int, score: float) -> None:
        """Fold one frame's color score into the running mean for this track."""
        key = (camera_id, track_id)
        rec = self._tracks.get(key)
        if rec is None:
            self._tracks[key] = _TrackColorScore(score, 1)
        else:
            rec.total += score
            rec.count += 1

    def mean_color_score(self, camera_id: str, track_id: int) -> float:
        """Mean uniform score observed for this track (0.0 if never observed)."""
        rec = self._tracks.get((camera_id, track_id))
        return rec.total / rec.count if rec is not None and rec.count else 0.0

    def is_staff(self, camera_id: str, track_id: int, dwell_ms: int = 0) -> bool:
        """Staff if the uniform mean clears the threshold (primary), else long presence."""
        if self.mean_color_score(camera_id, track_id) >= self.threshold:
            return True
        return self.presence_fallback_ms is not None and dwell_ms >= self.presence_fallback_ms
