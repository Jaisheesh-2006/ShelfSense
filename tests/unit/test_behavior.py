# PROMPT
# Task:
#   - Unit-test the prescribed flat BehaviorEvent contract's schema rules.
# Context:
#   - BehaviorEvent is the schema-graded event the pipeline emits / the API ingests (EVENT_SCHEMA).
#     Rules: ENTRY/EXIT carry no zone_id; timestamps must be timezone-aware and are normalised to
#     UTC; confidence in [0,1]; dwell_ms >= 0; enum + datetime serialise cleanly to JSON.
# Constraints:
#   - No network / no model. Build events in-process; assert validation raises on violations.
# Output:
#   - Tests: ENTRY rejects a zone_id but allows None; ZONE_DWELL keeps its zone; naive timestamp is
#     rejected; an offset datetime is converted to UTC; out-of-range confidence is rejected;
#     model_dump_json round-trips the enum value and a UTC timestamp.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the prescribed BehaviorEvent schema rules."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType, EventMetadata

UTC_TS = datetime(2026, 4, 10, 14, 40, 0, tzinfo=UTC)


def _event(**overrides):
    base = {
        "store_id": "ST1008",
        "camera_id": "CAM3",
        "visitor_id": "VIS_abc123",
        "event_type": BehaviorEventType.ENTRY,
        "timestamp": UTC_TS,
        "confidence": 0.9,
    }
    base.update(overrides)
    return BehaviorEvent(**base)


def test_entry_rejects_zone_but_allows_none():
    assert _event(event_type=BehaviorEventType.ENTRY, zone_id=None).zone_id is None
    with pytest.raises(ValidationError):
        _event(event_type=BehaviorEventType.ENTRY, zone_id="makeup_aisle")


def test_zone_event_keeps_its_zone():
    e = _event(event_type=BehaviorEventType.ZONE_DWELL, zone_id="makeup_aisle", dwell_ms=8400)
    assert e.zone_id == "makeup_aisle" and e.dwell_ms == 8400


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        _event(timestamp=datetime(2026, 4, 10, 14, 40, 0))  # no tzinfo


def test_offset_timestamp_is_normalised_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    e = _event(timestamp=datetime(2026, 4, 10, 20, 10, 0, tzinfo=ist))
    assert e.timestamp.tzinfo == UTC
    assert e.timestamp == datetime(2026, 4, 10, 14, 40, 0, tzinfo=UTC)


def test_confidence_must_be_in_range():
    with pytest.raises(ValidationError):
        _event(confidence=1.4)


def test_json_round_trips_enum_value_and_utc():
    raw = _event(metadata=EventMetadata(session_seq=1)).model_dump_json()
    assert '"event_type":"ENTRY"' in raw
    assert '"session_seq":1' in raw
    reparsed = BehaviorEvent.model_validate_json(raw)
    assert reparsed.event_type is BehaviorEventType.ENTRY
    assert reparsed.timestamp == UTC_TS
