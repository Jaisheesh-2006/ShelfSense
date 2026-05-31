"""Entrance line-crossing detection — the footfall core.

Given a stream of per-track foot-point positions and the calibrated `EntranceLine`, decides when a
track has *crossed* the line and in which direction:

    OUTSIDE -> INSIDE  => ENTRY  (mint a new visitor_id, start a visit)
    INSIDE  -> OUTSIDE => EXIT   (close the visit)

This is the part of footfall counting that we own (ByteTrack provides identity; this provides the
business event), so it is a **pure, deterministic state machine** with no dependency on YOLO,
datetime, or config — making it fully unit-testable.

Robustness choices:
- We act only on a *confirmed change of side*. A track's first definite sighting only seeds its
  side (someone already inside when the clip starts must not generate a phantom ENTRY).
- Points exactly on the line (side()==0) are ignored as ambiguous.
- Flicker near the threshold is debounced: a new side must persist for `confirm_frames` consecutive
  samples before a crossing is committed (EDGE_CASES: zone-boundary flicker).

visitor_id is minted per visit at ENTRY. There is no Re-ID yet (Slice 2.4): a visitor_id is unique
per CAM3 track, not yet deduplicated across cameras, and REENTRY is not detected here.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from shelfsense_common.contracts import BehaviorEventType, EntranceLine


def _default_visitor_id() -> str:
    """A short, unique visit token (e.g. VIS_c8a2f1), matching the EVENT_SCHEMA example."""
    return f"VIS_{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class Crossing:
    """A confirmed entrance crossing — the raw material for an ENTRY/EXIT BehaviorEvent."""

    track_id: int
    visitor_id: str
    event_type: BehaviorEventType  # ENTRY or EXIT
    session_seq: int
    ts_ms: int  # source media time of the crossing frame
    confidence: float


class CrossingDetector:
    """Stateful per-track line-crossing detector for one entrance camera.

    Feed it every track observation for the camera, in frame order, via `update()`. It returns the
    crossing events (usually none) triggered by that observation.
    """

    def __init__(
        self,
        line: EntranceLine,
        *,
        confirm_frames: int = 1,
        id_factory: Callable[[], str] = _default_visitor_id,
    ) -> None:
        if confirm_frames < 1:
            raise ValueError("confirm_frames must be >= 1")
        self._line = line
        self._confirm_frames = confirm_frames
        self._id_factory = id_factory
        self._committed_side: dict[int, int] = {}  # track_id -> last confirmed side (+1/-1)
        self._pending: dict[int, tuple[int, int]] = {}  # track_id -> (candidate_side, count)
        self._visitor: dict[int, str] = {}  # track_id -> current visitor_id
        self._seq: dict[str, int] = {}  # visitor_id -> last session_seq issued

    def update(
        self, track_id: int, foot_x: float, foot_y: float, ts_ms: int, confidence: float
    ) -> list[Crossing]:
        """Process one track's foot-point for one frame; return any confirmed crossings."""
        side = self._line.side(foot_x, foot_y)
        if side == 0:  # exactly on the line — ambiguous, ignore
            return []

        committed = self._committed_side.get(track_id)
        if committed is None:  # first definite sighting: seed side, emit nothing
            self._committed_side[track_id] = side
            self._pending.pop(track_id, None)
            return []

        if side == committed:  # back on the committed side: cancel any pending flip
            self._pending.pop(track_id, None)
            return []

        # Side differs from committed -> candidate crossing; require it to persist (debounce).
        cand, count = self._pending.get(track_id, (side, 0))
        if cand != side:
            cand, count = side, 0
        count += 1
        if count < self._confirm_frames:
            self._pending[track_id] = (cand, count)
            return []

        # Confirmed crossing.
        self._pending.pop(track_id, None)
        self._committed_side[track_id] = side
        is_entry = side == self._line.inside_sign
        event_type = BehaviorEventType.ENTRY if is_entry else BehaviorEventType.EXIT
        visitor_id = self._visitor_id_for(track_id, is_entry)
        seq = self._next_seq(visitor_id)
        return [
            Crossing(
                track_id=track_id,
                visitor_id=visitor_id,
                event_type=event_type,
                session_seq=seq,
                ts_ms=ts_ms,
                confidence=confidence,
            )
        ]

    def _visitor_id_for(self, track_id: int, is_entry: bool) -> str:
        """ENTRY starts a fresh visit; EXIT reuses the track's visit (minting one if we only caught
        the exit of someone already inside at clip start)."""
        if is_entry:
            visitor_id = self._id_factory()
        else:
            visitor_id = self._visitor.get(track_id) or self._id_factory()
        self._visitor[track_id] = visitor_id
        return visitor_id

    def _next_seq(self, visitor_id: str) -> int:
        seq = self._seq.get(visitor_id, 0) + 1
        self._seq[visitor_id] = seq
        return seq
