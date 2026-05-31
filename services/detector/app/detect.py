"""Person detection with YOLO.

`PersonDetector` wraps the Ultralytics model (imported lazily so unit tests don't need it). The
box-filtering logic is a separate pure function, `boxes_to_detections`, so it can be tested
offline without a model or GPU.
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from shelfsense_common.contracts import BBox, Detection

# A raw detection from the model: (class_id, confidence, (x1, y1, x2, y2)) in pixels.
RawBox = tuple[int, float, tuple[float, float, float, float]]


def boxes_to_detections(
    raw_boxes: Iterable[RawBox],
    person_class_id: int,
    conf_threshold: float,
) -> list[Detection]:
    """Keep only person boxes above the confidence threshold; convert xyxy -> our BBox (x,y,w,h)."""
    detections: list[Detection] = []
    for class_id, confidence, (x1, y1, x2, y2) in raw_boxes:
        if class_id != person_class_id or confidence < conf_threshold:
            continue
        detections.append(
            Detection(
                bbox=BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1),
                confidence=confidence,
                class_id=class_id,
            )
        )
    return detections


class PersonDetector:
    """Runs YOLO on a frame and returns person detections."""

    def __init__(self, model_path: str, confidence: float, person_class_id: int = 0) -> None:
        from ultralytics import YOLO  # lazy: heavy import (torch), not needed in unit tests

        self._model = YOLO(model_path)
        self.confidence = confidence
        self.person_class_id = person_class_id

    def detect(self, image: np.ndarray) -> list[Detection]:
        # Ask YOLO for the person class only, above our confidence threshold.
        results = self._model.predict(
            image,
            conf=self.confidence,
            classes=[self.person_class_id],
            verbose=False,
        )
        raw: list[RawBox] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                raw.append((class_id, confidence, (x1, y1, x2, y2)))
        return boxes_to_detections(raw, self.person_class_id, self.confidence)
