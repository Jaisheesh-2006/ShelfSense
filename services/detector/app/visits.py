"""Visitor identity registry (gallery-backed for cross-camera dedup, Slice 2.4).

A `visitor_id` is the GLOBAL, de-duplicated identity of a shopper. The registry maps each per-camera
track to a global id by asking the `ReIDGallery` to match the track's appearance signature against
known visitors (ADR-0008): the same person on CAM1 and CAM2, or returning after leaving, resolves to
ONE id instead of several. This is the basis for "unique visitors" (ADR-0007).

Resolution is **lazy and cached**: the first time a track needs an id (its first emitted event, ~2s
in, once its signature is stable) we hit the gallery; afterwards the `(camera, track)` mapping is
cached so every later event reuses the same id. `session_seq` is one increasing ordinal per visitor.

Pure given the gallery (which is itself pure over signatures), so it is fully unit-testable.
"""

from __future__ import annotations

import numpy as np

from app.reid import ReIDGallery, Resolution


class VisitorRegistry:
    """Resolves per-camera tracks to global visitor_ids via the Re-ID gallery; owns session_seq."""

    def __init__(self, gallery: ReIDGallery) -> None:
        self._gallery = gallery
        self._ids: dict[tuple[str, int], str] = {}  # (camera_id, track_id) -> global visitor_id
        self._seq: dict[str, int] = {}  # visitor_id -> last session_seq issued

    def is_resolved(self, camera_id: str, track_id: int) -> bool:
        """True once this track has been assigned a global id (so signature accrual can stop)."""
        return (camera_id, track_id) in self._ids

    def resolve(
        self, camera_id: str, track_id: int, signature: np.ndarray, ts_ms: int
    ) -> Resolution:
        """Return the global identity for a track. First call matches via the gallery; then cached.

        Only the first (uncached) resolve can report `is_new`/`is_reentry`; cached calls report a
        benign reuse so callers don't double-emit REENTRY.
        """
        key = (camera_id, track_id)
        cached = self._ids.get(key)
        if cached is not None:
            return Resolution(cached, is_new=False, is_reentry=False)
        res = self._gallery.resolve(signature, ts_ms)
        self._ids[key] = res.visitor_id
        return res

    def next_seq(self, visitor_id: str) -> int:
        """Return the next 1-based ordinal for an event in this visitor's session."""
        seq = self._seq.get(visitor_id, 0) + 1
        self._seq[visitor_id] = seq
        return seq

    @property
    def unique_count(self) -> int:
        """Distinct global visitors minted (deduplicated across cameras)."""
        return self._gallery.unique_count
