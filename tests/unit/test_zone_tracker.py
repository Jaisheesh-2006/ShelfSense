# PROMPT
# Task:
#   - Unit-test the ZoneTracker presence/dwell state machine.
# Context:
#   - Per camera (one fixed zone): a track that is present >= min_zone_dwell emits ZONE_ENTER; every
#     dwell_interval of continuous presence emits a ZONE_DWELL (running dwell_ms); absence beyond
#     exit_grace emits ZONE_EXIT (total dwell_ms). flush() closes still-present tracks at clip end.
#     Brief, never-entered tracks are dropped silently (pass-through noise filter).
# Constraints:
#   - Pure logic, no video. Use small explicit thresholds and feed synthetic (track, ts) samples.
# Output:
#   - Tests: ENTER only after min dwell; brief track -> no events; ZONE_DWELL on interval ticks;
#     ZONE_EXIT after grace with correct total dwell_ms; flush emits EXIT for an active visitor.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the ZoneTracker presence/dwell state machine."""

from app.zone_tracker import ZoneTracker
from shelfsense_common.contracts import BehaviorEventType

ZONE = "makeup_aisle"


def _tracker() -> ZoneTracker:
    # Small thresholds so the maths is obvious: enter@1s, dwell tick@3s, exit@1.5s absence.
    return ZoneTracker(
        zone=ZONE, min_zone_dwell_ms=1000, dwell_interval_ms=3000, exit_grace_ms=1500
    )


def test_enter_only_after_min_dwell():
    zt = _tracker()
    assert zt.observe(1, 0, 0.9) == []  # first sighting: seed, no event
    assert zt.observe(1, 500, 0.9) == []  # 0.5s present: below min dwell
    events = zt.observe(1, 1000, 0.9)  # 1.0s present: ZONE_ENTER
    assert len(events) == 1
    assert events[0].event_type is BehaviorEventType.ZONE_ENTER
    assert events[0].zone == ZONE and events[0].dwell_ms == 0


def test_brief_track_produces_no_events():
    zt = _tracker()
    zt.observe(2, 0, 0.9)  # seen once
    zt.observe(2, 400, 0.9)  # still under min dwell, then disappears
    assert zt.sweep(3000) == []  # absent beyond grace, never entered -> dropped silently


def test_zone_dwell_emitted_on_interval_boundaries():
    zt = _tracker()
    zt.observe(3, 0, 0.9)
    zt.observe(3, 1000, 0.9)  # ENTER
    dwell = zt.observe(3, 3000, 0.9)  # 3s present -> first DWELL tick
    assert len(dwell) == 1 and dwell[0].event_type is BehaviorEventType.ZONE_DWELL
    assert dwell[0].dwell_ms == 3000
    assert zt.observe(3, 4000, 0.9) == []  # 4s: no new tick yet
    dwell2 = zt.observe(3, 6500, 0.9)  # 6.5s -> second tick
    assert len(dwell2) == 1 and dwell2[0].dwell_ms == 6500


def test_zone_exit_after_grace_with_total_dwell():
    zt = _tracker()
    zt.observe(4, 0, 0.9)
    zt.observe(4, 1000, 0.8)  # ENTER
    zt.observe(4, 2000, 0.7)  # last seen at 2000
    events = zt.sweep(4000)  # 2s absent > 1.5s grace -> EXIT
    assert len(events) == 1
    exit_ev = events[0]
    assert exit_ev.event_type is BehaviorEventType.ZONE_EXIT
    assert exit_ev.dwell_ms == 2000  # 2000 (last_seen) - 0 (first_seen)
    assert exit_ev.ts_ms == 2000  # stamped at last real sighting, not the sweep time


def test_flush_closes_active_visitor():
    zt = _tracker()
    zt.observe(5, 0, 0.9)
    zt.observe(5, 1000, 0.9)  # ENTER, still present
    events = zt.flush(1000)
    assert len(events) == 1 and events[0].event_type is BehaviorEventType.ZONE_EXIT
