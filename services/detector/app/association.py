"""Tracking-based track association — spatio-temporal tracklet stitching (ADR-0037).

The colour/CNN appearance Re-ID (`reid.py` / `embedding.py`) is the only thing currently re-linking
a shopper whose ByteTrack `track_id` fragments (a turn-around, a brief occlusion). On overhead CCTV
appearance is **non-discriminative** (measured — ADR-0036: same person front/back is *farther* apart
than two different people), so that re-link silently fails and one person SPLITS into several
`visitor_id`s (Store_2: one staffer → 4 ids). Appearance was the wrong tool.

The reliable cue we were ignoring is **motion**: a person cannot teleport, so a track that dies at
position *P*, time *T* and a NEW track born near *P* soon after is the **same person**, whatever
their colour histogram did. This module stitches fragmented per-camera `track_id`s into
stable LOCAL track ids with a constant-velocity spatio-temporal gate (last-seen position + a short
time gap + velocity prediction), entirely independent of pixels.

It runs **per camera** (positions are camera-local) and **before** the appearance gallery, so:
  - WITHIN a camera, fragments collapse by motion — the dominant over-split fix; and
  - ACROSS cameras, the appearance gallery still de-dups one shopper seen on several cameras — the
    appearance Re-ID is kept as the FALLBACK, not removed.

Pluggable like the VLM / embedder: `build_associator` returns an `IdentityAssociator` (raw id is the
local id — the legacy appearance-only path) for ``TRACK_ASSOCIATION="appearance"``, else the
`MotionTrackAssociator`. Pure (positions + time only, no OpenCV / torch) so it is fully
unit-testable and can never couple the acceptance gate to a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TrackAssociator(Protocol):
    """Maps a raw per-frame ByteTrack id to a stable LOCAL track id (stitching fragments)."""

    def assign(self, track_id: int, foot_x: float, foot_y: float, ts_ms: int) -> int: ...


class IdentityAssociator:
    """No stitching: the raw ByteTrack id *is* the local id (the legacy appearance-only path).

    Selected by ``TRACK_ASSOCIATION="appearance"`` — the detector then behaves exactly as it did
    before this ADR, with the colour/CNN gallery doing all the re-linking. The documented fallback.
    """

    def assign(self, track_id: int, foot_x: float, foot_y: float, ts_ms: int) -> int:
        return track_id


@dataclass
class _LocalTrack:
    """A stitched local track: where it was last seen and how fast it was moving (px / ms)."""

    local_id: int
    last_x: float
    last_y: float
    last_ts: int
    vx: float = 0.0
    vy: float = 0.0


class MotionTrackAssociator:
    """Stitches fragmented per-camera tracks into stable local ids by spatio-temporal continuity.

    For each new raw `track_id` we look for a recently-LOST local track whose constant-velocity
    prediction lands within `max_jump_px` of the new track's first foot-point, and whose absence
    sits in the ``(min_gap_ms, max_gap_ms]`` window. The window's lower bound is the safety guard: a
    track still alive this frame (or merely processed later in the same frame) has a sub-frame gap
    and is excluded, so two people coexisting on screen can never be merged into one id. The upper
    bound stops linking across gaps so long a *different* person could have walked into the spot.
    """

    def __init__(self, *, max_gap_ms: float, min_gap_ms: float, max_jump_px: float) -> None:
        self._max_gap_ms = max_gap_ms
        self._min_gap_ms = min_gap_ms
        self._max_jump_px = max_jump_px
        self._next_local = 0
        self._raw_to_local: dict[int, int] = {}
        self._locals: dict[int, _LocalTrack] = {}

    def assign(self, track_id: int, foot_x: float, foot_y: float, ts_ms: int) -> int:
        # Already-bound raw track → just advance its local's motion state.
        bound = self._raw_to_local.get(track_id)
        if bound is not None:
            self._advance(self._locals[bound], foot_x, foot_y, ts_ms)
            return bound
        # New raw track → try to continue a recently-lost local (stitch); else mint a fresh one.
        cand = self._best_candidate(foot_x, foot_y, ts_ms)
        if cand is not None:
            self._raw_to_local[track_id] = cand
            self._advance(self._locals[cand], foot_x, foot_y, ts_ms)
            return cand
        return self._mint(track_id, foot_x, foot_y, ts_ms)

    def _best_candidate(self, fx: float, fy: float, ts_ms: int) -> int | None:
        """Nearest lost local whose predicted position is within the spatial + temporal gates."""
        best_id: int | None = None
        best_d = float("inf")
        for lt in self._locals.values():
            gap = ts_ms - lt.last_ts
            if gap <= self._min_gap_ms or gap > self._max_gap_ms:
                continue  # still live this frame, or gone too long to trust the link
            px = lt.last_x + lt.vx * gap  # constant-velocity prediction of where it would be now
            py = lt.last_y + lt.vy * gap
            d = ((fx - px) ** 2 + (fy - py) ** 2) ** 0.5
            if d <= self._max_jump_px and d < best_d:
                best_d, best_id = d, lt.local_id
        return best_id

    def _advance(self, lt: _LocalTrack, fx: float, fy: float, ts_ms: int) -> None:
        """Update a local's last position and EMA-smoothed velocity (robust to per-frame jitter)."""
        dt = ts_ms - lt.last_ts
        if dt > 0:
            lt.vx = 0.5 * lt.vx + 0.5 * (fx - lt.last_x) / dt
            lt.vy = 0.5 * lt.vy + 0.5 * (fy - lt.last_y) / dt
        lt.last_x, lt.last_y, lt.last_ts = fx, fy, ts_ms

    def _mint(self, track_id: int, fx: float, fy: float, ts_ms: int) -> int:
        self._next_local += 1
        lid = self._next_local
        self._locals[lid] = _LocalTrack(lid, fx, fy, ts_ms)
        self._raw_to_local[track_id] = lid
        return lid


def build_associator(settings, frame_w: int, frame_h: int) -> TrackAssociator:
    """Construct the per-camera associator, or the legacy pass-through (appearance-only) fallback.

    Returns `IdentityAssociator` when ``TRACK_ASSOCIATION`` != "motion", so the detector degrades to
    the appearance gallery alone. The motion gate is resolution- and frame-rate-aware: the spatial
    jump is a fraction of the frame's longest side, and the minimum gap is lifted above one sampled
    frame interval so a track merely not-yet-processed this frame can never be mistaken for lost.
    """
    if settings.track_association.lower() != "motion":
        return IdentityAssociator()
    frame_interval_ms = 1000.0 / max(settings.tracker_sample_fps, 1.0)
    min_gap_ms = max(float(settings.stitch_min_gap_ms), 1.5 * frame_interval_ms)
    max_jump_px = settings.stitch_max_jump_frac * max(frame_w, frame_h)
    return MotionTrackAssociator(
        max_gap_ms=float(settings.stitch_max_gap_ms),
        min_gap_ms=min_gap_ms,
        max_jump_px=max_jump_px,
    )
