"""Pure detection-quality gating helpers (ADR-0029).

Counting is **identity-honest**: a person contributes to the unique-visitor count only as a *solid*
track. The geometric pieces of that gate live elsewhere and are already pure/tested — sustained
presence (`zone_tracker`), on the walkable floor (`FloorRegion.contains`), and store-interior vs
mall pass-by (`EntranceLine.is_inside`). This module adds the remaining pure piece: a **box-size**
gate that drops tiny far/reflection blobs (e.g. mall pedestrians seen small through the glass).

Kept separate from the detector loop (no OpenCV/YOLO) so the policy is unit-testable in isolation.
"""

from __future__ import annotations


def box_area_fraction(w: float, h: float, frame_w: int, frame_h: int) -> float:
    """Bounding-box area as a fraction (0..1) of the frame area. 0 for empty box/frame."""
    area = max(0.0, w) * max(0.0, h)
    total = float(frame_w) * float(frame_h)
    return area / total if total > 0 else 0.0


def passes_size_gate(w: float, h: float, frame_w: int, frame_h: int, min_frac: float) -> bool:
    """True if the box is large enough to count (or the gate is disabled with min_frac <= 0)."""
    if min_frac <= 0:
        return True
    return box_area_fraction(w, h, frame_w, frame_h) >= min_frac
