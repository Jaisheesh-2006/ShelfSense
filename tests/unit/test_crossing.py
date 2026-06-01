# PROMPT
# Task:
#   - Unit-test the entrance line-crossing state machine that turns tracked foot-points into
#     ENTRY/EXIT events (the footfall core).
# Context:
#   - CrossingDetector(line) tracks each track_id's side of the line; OUTSIDE->INSIDE => ENTRY,
#     INSIDE->OUTSIDE => EXIT. First sighting only seeds the side; on-line points are ignored;
#     a side flip must persist confirm_frames samples (flicker debounce). Identity (visitor_id/seq)
#     is NOT minted here anymore (ADR-0007 -> VisitorRegistry); a Crossing carries only track_id,
#     event_type, ts_ms, confidence.
# Constraints:
#   - Pure logic only (no YOLO/datetime/config/identity). Use a simple horizontal line so the side
#     maths is obvious.
# Output:
#   - Tests: ENTRY on inbound cross; EXIT on the return crossing; a person already inside at first
#     sighting yields no ENTRY; single-frame flicker is debounced; a point on the line is ignored.
# CHANGES MADE:
#   - Dropped visitor_id/session_seq assertions and the injected id_factory (identity moved to the
#     VisitorRegistry); tests now assert the side-machine behaviour only.
"""Unit tests for the CrossingDetector footfall state machine."""

from app.crossing import CrossingDetector
from shelfsense_common.contracts import BehaviorEventType, EntranceLine

# Horizontal line at y=100; inside_sign=-1 => smaller y (upper) is inside, matching image coords.
# side(px,py) = (x2-x1)*(py-y1) = 100*(py-100): py>100 -> +1 (outside), py<100 -> -1 (inside).
LINE = EntranceLine(x1=0, y1=100, x2=100, y2=100, inside_sign=-1)


def test_outside_to_inside_emits_entry():
    det = CrossingDetector(LINE, confirm_frames=1)
    assert det.update(1, 50, 150, ts_ms=0, confidence=0.9) == []  # seed outside
    crosses = det.update(1, 50, 50, ts_ms=100, confidence=0.8)  # cross inside
    assert len(crosses) == 1
    assert crosses[0].event_type is BehaviorEventType.ENTRY
    assert crosses[0].track_id == 1
    assert crosses[0].ts_ms == 100


def test_return_crossing_emits_exit():
    det = CrossingDetector(LINE, confirm_frames=1)
    det.update(1, 50, 150, ts_ms=0, confidence=0.9)  # seed outside
    det.update(1, 50, 50, ts_ms=100, confidence=0.9)  # ENTRY
    crosses = det.update(1, 50, 150, ts_ms=200, confidence=0.7)  # back outside => EXIT
    assert len(crosses) == 1
    assert crosses[0].event_type is BehaviorEventType.EXIT


def test_person_already_inside_does_not_create_entry():
    det = CrossingDetector(LINE, confirm_frames=1)
    assert det.update(2, 50, 40, ts_ms=0, confidence=0.9) == []  # first sighting already inside
    assert det.update(2, 50, 30, ts_ms=100, confidence=0.9) == []  # still inside, no event


def test_single_frame_flicker_is_debounced():
    det = CrossingDetector(LINE, confirm_frames=2)
    det.update(3, 50, 150, ts_ms=0, confidence=0.9)  # seed outside
    assert det.update(3, 50, 50, ts_ms=100, confidence=0.9) == []  # 1 inside sample: not yet
    assert det.update(3, 50, 150, ts_ms=200, confidence=0.9) == []  # flicked back: cancelled
    # A sustained crossing (two consecutive inside samples) does fire.
    assert det.update(3, 50, 50, ts_ms=300, confidence=0.9) == []  # count 1
    crosses = det.update(3, 50, 40, ts_ms=400, confidence=0.9)  # count 2 -> confirmed
    assert len(crosses) == 1 and crosses[0].event_type is BehaviorEventType.ENTRY


def test_point_exactly_on_line_is_ignored():
    det = CrossingDetector(LINE, confirm_frames=1)
    det.update(4, 50, 150, ts_ms=0, confidence=0.9)  # seed outside
    assert det.update(4, 50, 100, ts_ms=100, confidence=0.9) == []  # exactly on line -> ignored
    # Still treated as outside; crossing inside afterwards still works.
    crosses = det.update(4, 50, 50, ts_ms=200, confidence=0.9)
    assert len(crosses) == 1 and crosses[0].event_type is BehaviorEventType.ENTRY
