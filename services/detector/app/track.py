"""Multi-object tracking with ByteTrack (via Ultralytics).

`PersonTracker` wraps Ultralytics' built-in ByteTrack so consecutive frames of one camera produce
*stable* `track_id`s for the same person — the prerequisite for counting entries without double
counting (a per-frame detection has no identity; a track does). The heavy model import is lazy so
unit tests don't need torch.

As with detection, the part we own and can test offline — turning raw tracker output into our
`Track` records — is a separate pure function, `boxes_to_tracks`. The ByteTrack association itself
is library code, validated empirically in scripts/validate_entrance.py rather than unit-tested.

Tracking is stateful per video sequence: ByteTrack carries Kalman/association state across calls.
Process one camera's frames in order, then call `reset()` before a different camera so identities
from one clip never leak into another.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict
from shelfsense_common.contracts import BBox

# A raw tracked box from the model: (track_id, class_id, confidence, (x1, y1, x2, y2)) in pixels.
# track_id is None for a detection ByteTrack did not (yet) associate to a track.
RawTrack = tuple[int | None, int, float, tuple[float, float, float, float]]


class Track(BaseModel):
    """One tracked person in a single frame: a stable id plus where they are."""

    model_config = ConfigDict(frozen=True)

    track_id: int
    bbox: BBox
    confidence: float

    @property
    def foot_point(self) -> tuple[float, float]:
        """Bottom-centre — where the person stands; used for line/zone tests (not box centre)."""
        return self.bbox.foot_point


def boxes_to_tracks(
    raw_tracks: Iterable[RawTrack],
    person_class_id: int,
    conf_threshold: float,
) -> list[Track]:
    """Keep confident person boxes that ByteTrack assigned an id; convert xyxy -> our BBox.

    Detections without a track_id (unassociated) are dropped here: a footfall count must be based
    on identified tracks, not anonymous boxes.
    """
    tracks: list[Track] = []
    for track_id, class_id, confidence, (x1, y1, x2, y2) in raw_tracks:
        if track_id is None or class_id != person_class_id or confidence < conf_threshold:
            continue
        tracks.append(
            Track(
                track_id=int(track_id),
                bbox=BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1),
                confidence=confidence,
            )
        )
    return tracks


class PersonTracker:
    """Runs YOLO+ByteTrack on a stream of frames, returning identified person tracks per frame."""

    def __init__(
        self,
        model_path: str,
        confidence: float,
        person_class_id: int = 0,
        tracker_cfg: str = "bytetrack.yaml",
    ) -> None:
        from ultralytics import YOLO  # lazy: heavy import (torch), not needed in unit tests

        self._model = YOLO(model_path)
        self.confidence = confidence
        self.person_class_id = person_class_id
        self.tracker_cfg = self._resolve_tracker_cfg(tracker_cfg)

    @staticmethod
    def _resolve_tracker_cfg(cfg: str) -> str:
        """Use a tracker yaml shipped next to this module (e.g. our tuned one) if it exists; else
        pass the name through to Ultralytics' built-ins (e.g. 'bytetrack.yaml')."""
        local = Path(__file__).parent / "trackers" / cfg
        return str(local) if local.exists() else cfg

    def update(self, image: np.ndarray) -> list[Track]:
        """Feed the next frame of the current camera sequence; return its tracks."""
        results = self._model.track(
            image,
            conf=self.confidence,
            classes=[self.person_class_id],
            tracker=self.tracker_cfg,
            persist=True,  # keep association state across frames of this sequence
            verbose=False,
        )
        raw: list[RawTrack] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                track_id = None if box.id is None else int(box.id[0])
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                raw.append((track_id, class_id, confidence, (x1, y1, x2, y2)))
        return boxes_to_tracks(raw, self.person_class_id, self.confidence)

    def reset(self) -> None:
        """Clear tracker state between camera sequences so ids don't carry over."""
        predictor = getattr(self._model, "predictor", None)
        trackers = getattr(predictor, "trackers", None) if predictor is not None else None
        if trackers:
            for tracker in trackers:
                tracker.reset()
