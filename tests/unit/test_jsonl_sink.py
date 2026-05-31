# PROMPT
# Task:
#   - Unit-test the JSONL event sink the detection layer writes behavioural events to.
# Context:
#   - JsonlEventSink(path) is a context manager that appends one BehaviorEvent per line as JSON,
#     creating parent directories. JSONL (not a JSON array) keeps the file append-only and the
#     API can ingest it line-by-line (ADR-0005: JSONL + idempotent ingest replaces the broker).
# Constraints:
#   - No network. Write to a pytest tmp_path; read the file back and parse each line as JSON.
# Output:
#   - Tests: two events produce two valid JSON lines preserving event_type/visitor_id; the sink
#     creates a missing parent directory; appending reopens and adds without truncating.
"""Unit tests for JsonlEventSink."""
import json
from datetime import UTC, datetime

from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType
from shelfsense_common.sinks import JsonlEventSink

UTC_TS = datetime(2026, 4, 10, 14, 40, 0, tzinfo=UTC)


def _event(visitor_id: str, event_type: BehaviorEventType) -> BehaviorEvent:
    return BehaviorEvent(
        store_id="ST1008",
        camera_id="CAM3",
        visitor_id=visitor_id,
        event_type=event_type,
        timestamp=UTC_TS,
        confidence=0.9,
    )


def test_two_events_write_two_valid_json_lines(tmp_path):
    path = tmp_path / "events" / "behavior.jsonl"  # parent dir does not exist yet
    with JsonlEventSink(path) as sink:
        sink.write(_event("VIS_1", BehaviorEventType.ENTRY))
        sink.write(_event("VIS_1", BehaviorEventType.EXIT))

    assert path.exists()  # parent directory was created
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["event_type"] == "ENTRY" and first["visitor_id"] == "VIS_1"
    assert second["event_type"] == "EXIT"


def test_append_does_not_truncate(tmp_path):
    path = tmp_path / "behavior.jsonl"
    with JsonlEventSink(path) as sink:
        sink.write(_event("VIS_1", BehaviorEventType.ENTRY))
    with JsonlEventSink(path) as sink:  # reopen
        sink.write(_event("VIS_2", BehaviorEventType.ENTRY))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
