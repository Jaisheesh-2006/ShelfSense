# PROMPT
# Task:
#   - Unit-test boxes_to_detections (the pure YOLO post-filter) offline.
# Context:
#   - It keeps only the person class above a confidence threshold and converts xyxy->xywh, exposing a
#     foot_point used later for zone/line logic.
# Constraints:
#   - No YOLO model or GPU; mock raw boxes as plain (class_id, confidence, xyxy) tuples.
# Output:
#   - Tests: drop non-person class; drop below threshold; correct xywh + foot_point; empty input -> [].
# CHANGES MADE:
#   - Added the foot_point assertion and the empty-input case.
#   - Used plain tuples so the test needs no model.
"""Unit tests for the pure detection-filtering logic (no model / GPU needed)."""
from app.detect import boxes_to_detections

PERSON = 0
CAR = 2


def test_keeps_only_person_class():
    raw = [(PERSON, 0.9, (10, 20, 30, 60)), (CAR, 0.95, (0, 0, 5, 5))]
    dets = boxes_to_detections(raw, person_class_id=PERSON, conf_threshold=0.4)
    assert len(dets) == 1
    assert dets[0].class_id == PERSON


def test_drops_low_confidence():
    raw = [(PERSON, 0.30, (0, 0, 10, 10)), (PERSON, 0.80, (0, 0, 10, 20))]
    dets = boxes_to_detections(raw, PERSON, conf_threshold=0.4)
    assert len(dets) == 1
    assert dets[0].confidence == 0.80


def test_converts_xyxy_to_xywh_and_foot_point():
    [d] = boxes_to_detections([(PERSON, 0.9, (10, 20, 40, 80))], PERSON, 0.4)
    assert (d.bbox.x, d.bbox.y, d.bbox.w, d.bbox.h) == (10, 20, 30, 60)
    # foot point = bottom-centre, used later for zone/line mapping.
    assert d.bbox.foot_point == (25.0, 80.0)


def test_empty_input():
    assert boxes_to_detections([], PERSON, 0.4) == []
