# PROMPT
# Task:
#   - Unit-test that an event serializes to the expected JSON wire format.
# Context:
#   - make_event() wraps a payload in an envelope (event_type, schema_version, source, correlation_id);
#     that JSON is what the ingest/consumer side reads.
# Constraints:
#   - Assert the exact keys downstream depends on; no broker or network.
# Output:
#   - Tests: the detection event JSON has the expected envelope + nested payload fields; make_event
#     auto-generates event_id/correlation_id when omitted.
# CHANGES MADE:
#   - Asserted the exact JSON keys the consumer relies on; added the auto-generated-id case.
#   - NOTE: update when the schema migrates to the prescribed behavioural schema (ADR-0005, Slice 2.2).
"""Unit tests for event contracts: JSON serialization is the wire format on the stream."""
import json

from shelfsense_common.contracts import (
    BBox,
    Detection,
    DetectionCreated,
    EventType,
    make_event,
)


def test_detection_event_serializes_to_expected_json():
    ev = make_event(
        EventType.DETECTION_CREATED,
        DetectionCreated(
            camera_id="CAM3",
            frame_id=12,
            ts_ms=400,
            detections=[Detection(bbox=BBox(x=1, y=2, w=3, h=4), confidence=0.9)],
        ),
        source="detector",
        correlation_id="corr-123",
    )
    data = json.loads(ev.model_dump_json())

    assert data["event_type"] == "detection.created"
    assert data["schema_version"] == "1.0"
    assert data["source"] == "detector"
    assert data["correlation_id"] == "corr-123"
    assert data["payload"]["camera_id"] == "CAM3"
    assert data["payload"]["detections"][0]["confidence"] == 0.9
    assert "event_id" in data and "occurred_at" in data


def test_make_event_generates_ids_when_not_given():
    ev = make_event(
        EventType.DETECTION_CREATED,
        DetectionCreated(camera_id="CAM1", frame_id=0, ts_ms=0),
        source="detector",
    )
    assert ev.event_id
    assert ev.correlation_id
