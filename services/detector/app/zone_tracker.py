"""Zone presence & dwell detection — the per-camera engagement core.

For each tracked person on a camera, decides when they have meaningfully entered the camera's zone,
how long they dwell, and when they leave:

    present >= min_zone_dwell        => ZONE_ENTER   (filters brief pass-through noise)
    every dwell_interval of presence => ZONE_DWELL    (re-emitted; carries running dwell_ms)
    absent  >  exit_grace            => ZONE_EXIT     (carries total dwell_ms)

For v1 each camera maps to ONE primary zone (camera-level zones, DECISIONS PD-4), so the zone is
fixed per tracker; the same logic generalises to finer zones later via a zone per observation.

Like CrossingDetector this is a **pure, deterministic state machine** (no YOLO/datetime/config), so
it is fully unit-testable. The main loop feeds it the tracks present each frame and the media time;
identity (visitor_id) is attached downstream from the VisitorRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shelfsense_common.contracts import BehaviorEventType


@dataclass(frozen=True)
class ZoneEvent:
    """A zone presence event for one track — raw material for a ZONE_* BehaviorEvent."""

    track_id: int
    event_type: BehaviorEventType  # ZONE_ENTER | ZONE_DWELL | ZONE_EXIT
    zone: str
    ts_ms: int
    dwell_ms: int  # 0 for ENTER; running/total presence for DWELL/EXIT
    confidence: float


@dataclass
class _TrackState:
    first_seen_ms: int
    last_seen_ms: int
    last_confidence: float
    entered: bool = False
    dwell_ticks: int = 0  # number of dwell_interval boundaries already emitted


@dataclass
class ZoneTracker:
    """Tracks presence/dwell of people in one camera's zone."""

    zone: str
    min_zone_dwell_ms: int = 2000
    dwell_interval_ms: int = 30000
    exit_grace_ms: int = 2000
    _state: dict[int, _TrackState] = field(default_factory=dict)

    def observe(self, track_id: int, ts_ms: int, confidence: float) -> list[ZoneEvent]:
        """Record a track present this frame; emit ZONE_ENTER / ZONE_DWELL as they fall due."""
        st = self._state.get(track_id)
        if st is None:  # first sighting — start the presence clock, emit nothing yet
            self._state[track_id] = _TrackState(ts_ms, ts_ms, confidence)
            return []

        st.last_seen_ms = ts_ms
        st.last_confidence = confidence
        present_ms = ts_ms - st.first_seen_ms
        events: list[ZoneEvent] = []

        if not st.entered and present_ms >= self.min_zone_dwell_ms:
            st.entered = True
            events.append(
                ZoneEvent(track_id, BehaviorEventType.ZONE_ENTER, self.zone, ts_ms, 0, confidence)
            )

        if st.entered:
            while present_ms >= (st.dwell_ticks + 1) * self.dwell_interval_ms:
                st.dwell_ticks += 1
                events.append(
                    ZoneEvent(
                        track_id,
                        BehaviorEventType.ZONE_DWELL,
                        self.zone,
                        ts_ms,
                        present_ms,
                        confidence,
                    )
                )
        return events

    def sweep(self, now_ms: int) -> list[ZoneEvent]:
        """Emit ZONE_EXIT for tracks absent past exit_grace; drop brief, never-entered tracks."""
        events: list[ZoneEvent] = []
        for track_id, st in list(self._state.items()):
            if now_ms - st.last_seen_ms > self.exit_grace_ms:
                if st.entered:
                    events.append(self._exit_event(track_id, st))
                del self._state[track_id]
        return events

    def flush(self, now_ms: int) -> list[ZoneEvent]:
        """Close all still-present tracks at end of clip (entered ones get a ZONE_EXIT)."""
        events: list[ZoneEvent] = []
        for track_id, st in list(self._state.items()):
            if st.entered:
                events.append(self._exit_event(track_id, st))
        self._state.clear()
        return events

    def _exit_event(self, track_id: int, st: _TrackState) -> ZoneEvent:
        dwell = st.last_seen_ms - st.first_seen_ms
        return ZoneEvent(
            track_id,
            BehaviorEventType.ZONE_EXIT,
            self.zone,
            st.last_seen_ms,
            dwell,
            st.last_confidence,
        )
