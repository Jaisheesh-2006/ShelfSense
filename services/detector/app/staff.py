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


def dark_fraction(hsv: np.ndarray, v_max: int = DARK_V_MAX) -> float:
    """Fraction of pixels whose HSV Value channel <= v_max. Pure; `hsv` is an (H,W,3) uint8 array.

    Empty input -> 0.0. This is the per-region "how black is it" measure.
    """
    if hsv.size == 0:
        return 0.0
    value = hsv[:, :, 2]
    return float(np.count_nonzero(value <= v_max) / value.size)


def uniform_darkness(
    image: np.ndarray, x: int, y: int, w: int, h: int, v_max: int = DARK_V_MAX
) -> float:
    """Dark-uniform score in [0,1] for a person box: min(dark upper-body, dark lower-body).

    The min means a full black uniform scores high while a half-dark outfit scores low. Returns 0
    for an empty/zero box. Needs OpenCV (pixel work); the decision policy is in `StaffClassifier`.
    """
    import cv2  # local import: keep the decision logic importable without OpenCV

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
    mid = hsv.shape[0] // 2
    if mid < 1:
        return dark_fraction(hsv, v_max)
    upper = dark_fraction(hsv[:mid], v_max)
    lower = dark_fraction(hsv[mid:], v_max)
    return min(upper, lower)


@dataclass
class _TrackDarkness:
    total: float
    count: int


class StaffClassifier:
    """Accumulates per-frame dark-uniform scores per track, then decides `is_staff` by threshold.

    Pure given the scores (callers pass numbers, not pixels), so the policy is fully unit-testable.
    A track is staff if its mean darkness >= `threshold`. An optional presence fallback (off by
    default) also flags a track present beyond `presence_fallback_ms` even if not dark — useful for
    non-uniformed staff on longer/live footage, but off here because on a 2-min clip a browsing
    customer can dwell long too, and we only have two real customers to protect.
    """

    def __init__(self, threshold: float, presence_fallback_ms: int | None = None) -> None:
        self.threshold = threshold
        self.presence_fallback_ms = presence_fallback_ms
        self._tracks: dict[tuple[str, int], _TrackDarkness] = {}

    def observe(self, camera_id: str, track_id: int, darkness: float) -> None:
        """Fold one frame's darkness score into the running mean for this track."""
        key = (camera_id, track_id)
        rec = self._tracks.get(key)
        if rec is None:
            self._tracks[key] = _TrackDarkness(darkness, 1)
        else:
            rec.total += darkness
            rec.count += 1

    def mean_darkness(self, camera_id: str, track_id: int) -> float:
        """Mean dark-uniform score observed for this track (0.0 if never observed)."""
        rec = self._tracks.get((camera_id, track_id))
        return rec.total / rec.count if rec is not None and rec.count else 0.0

    def is_staff(self, camera_id: str, track_id: int, dwell_ms: int = 0) -> bool:
        """Staff if the dark-uniform mean clears the threshold (primary), else long presence."""
        if self.mean_darkness(camera_id, track_id) >= self.threshold:
            return True
        return self.presence_fallback_ms is not None and dwell_ms >= self.presence_fallback_ms
