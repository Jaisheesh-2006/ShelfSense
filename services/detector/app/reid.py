"""Lightweight appearance-based Re-Identification (ADR-0008, the chosen Option 1).

Goal: recognise that the same shopper seen on different cameras (or returning after leaving) is ONE
person, so we count *unique visitors* rather than per-camera tracks. We deliberately avoid a heavy
dedicated Re-ID model (extra weights, gate risk) and use a cheap **HSV colour-histogram signature**
+ nearest-neighbour matching — CPU-only and offline-safe, "close enough" for this systems challenge.

Two concerns are split so the decision logic is testable without a model:
- `appearance_signature(image, bbox)` extracts the signature from pixels (needs OpenCV).
- `signature_distance` and `ReIDGallery` are pure numpy/math and fully unit-testable.

Honest limitation (documented as an Assumption): on evening footage with many dark-clothed shoppers
and varied camera angles, colour histograms are noisy, so matching is imperfect — it may over- or
under-merge. We tune `max_distance` empirically and report the real effect, not claimed precision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

# Lazy/typing-only: cv2 is heavy and only needed for pixel extraction, not for matching logic.
HUE_BINS, SAT_BINS, VAL_BINS = 8, 8, 8
SIGNATURE_LEN = HUE_BINS * SAT_BINS * VAL_BINS


def appearance_signature(image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """L2-normalised HSV colour histogram of a person crop. Empty/zero crop -> zero vector."""
    import cv2  # local import: keep matching logic importable without OpenCV

    H, W = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros(SIGNATURE_LEN, dtype=np.float32)
    crop = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist(
        [hsv], [0, 1, 2], None, [HUE_BINS, SAT_BINS, VAL_BINS], [0, 180, 0, 256, 0, 256]
    )
    vec = hist.flatten().astype(np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def signature_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance in [0, 2]; 0 = identical. Assumes L2-normalised inputs (zero vec -> 1.0)."""
    if a.shape != b.shape:
        raise ValueError("signature shape mismatch")
    return float(1.0 - np.dot(a, b))


@dataclass
class _GalleryVisitor:
    visitor_id: str
    signature: np.ndarray  # running-averaged representative signature (renormalised)
    last_seen_ms: int
    samples: int


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving a track's signature against the gallery."""

    visitor_id: str
    is_new: bool
    is_reentry: bool


class ReIDGallery:
    """Nearest-signature gallery of global visitors. Pure: callers pass signatures, not pixels."""

    def __init__(
        self,
        max_distance: float = 0.35,
        reentry_min_gap_ms: int = 5000,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.max_distance = max_distance
        self.reentry_min_gap_ms = reentry_min_gap_ms
        # Deterministic by default (ADR-0021): visitors are numbered in discovery order
        # (VIS_0001, VIS_0002, ...). Detection/tracking are reproducible for a given clip+config, so
        # an identical re-run mints the SAME ids — which, with deterministic event_ids, makes
        # re-ingest idempotent instead of accumulating. Callers may inject an `id_factory` (tests).
        self._seq = 0
        self._id_factory = id_factory or self._next_sequential_id
        self._visitors: list[_GalleryVisitor] = []

    def _next_sequential_id(self) -> str:
        self._seq += 1
        return f"VIS_{self._seq:04d}"

    def resolve(self, signature: np.ndarray, ts_ms: int) -> Resolution:
        """Match a signature to the nearest visitor within max_distance, else mint a new one."""
        best: _GalleryVisitor | None = None
        best_d = float("inf")
        for v in self._visitors:
            d = signature_distance(signature, v.signature)
            if d < best_d:
                best_d, best = d, v

        if best is not None and best_d <= self.max_distance:
            is_reentry = (ts_ms - best.last_seen_ms) > self.reentry_min_gap_ms
            self._merge(best, signature, ts_ms)
            return Resolution(best.visitor_id, is_new=False, is_reentry=is_reentry)

        visitor_id = self._id_factory()
        self._visitors.append(_GalleryVisitor(visitor_id, signature.copy(), ts_ms, 1))
        return Resolution(visitor_id, is_new=True, is_reentry=False)

    def _merge(self, v: _GalleryVisitor, signature: np.ndarray, ts_ms: int) -> None:
        """Fold the new sample into the visitor's representative signature (running mean)."""
        blended = (v.signature * v.samples) + signature
        norm = float(np.linalg.norm(blended))
        v.signature = blended / norm if norm > 0 else blended
        v.samples += 1
        v.last_seen_ms = max(v.last_seen_ms, ts_ms)

    @property
    def unique_count(self) -> int:
        return len(self._visitors)
