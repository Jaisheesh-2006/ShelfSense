"""Entrance line-crossing detection — the footfall core.

Given a stream of per-track foot-point positions and the calibrated `EntranceLine`, decides when a
track has *crossed* the line and in which direction:

    OUTSIDE -> INSIDE  => ENTRY
    INSIDE  -> OUTSIDE => EXIT

This is the part of footfall counting that we own (ByteTrack provides identity; this provides the
business event), so it is a **pure, deterministic state machine** with no dependency on YOLO,
datetime, or config — making it fully unit-testable.

Robustness choices:
- We act only on a *confirmed change of side*. A track's first definite sighting only seeds its
  side (someone already inside when the clip starts must not generate a phantom ENTRY).
- Points exactly on the line (side()==0) are ignored as ambiguous.
- Flicker near the threshold is debounced: a new side must persist for `confirm_frames` consecutive
  samples before a crossing is committed (EDGE_CASES: zone-boundary flicker).

Identity is NOT minted here: `visitor_id`/`session_seq` come from the VisitorRegistry (ADR-0007),
attached by the caller — so a CAM3 shopper has one id whether we first see them browse or cross.
"""

from __future__ import annotations

from dataclasses import dataclass

from shelfsense_common.contracts import BehaviorEventType, EntranceLine


@dataclass(frozen=True)
class Crossing:
    """A confirmed entrance crossing — the raw material for an ENTRY/EXIT BehaviorEvent."""

    track_id: int
    event_type: BehaviorEventType  # ENTRY or EXIT
    ts_ms: int  # source media time of the crossing frame
    confidence: float


class CrossingDetector:
    """Stateful per-track line-crossing detector for one entrance camera.

    Feed it every track observation for the camera, in frame order, via `update()`. It returns the
    crossing events (usually none) triggered by that observation.
    """

    def __init__(self, line: EntranceLine, *, confirm_frames: int = 1) -> None:
        if confirm_frames < 1:
            raise ValueError("confirm_frames must be >= 1")
        self._line = line
        self._confirm_frames = confirm_frames
        self._committed_side: dict[int, int] = {}  # track_id -> last confirmed side (+1/-1)
        self._pending: dict[int, tuple[int, int]] = {}  # track_id -> (candidate_side, count)

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
        return [
            Crossing(track_id=track_id, event_type=event_type, ts_ms=ts_ms, confidence=confidence)
        ]
