"""Pose-based group splitting (ADR-0038) — off by default, gate-safe.

On overhead CCTV, YOLO+ByteTrack draws **one** box around 2-4 tightly-packed shoppers, so a group
collapses into a single `track_id` and the unique-visitor count is *deflated* (Store_2: 17 detected
vs 22 GT). This is a detection-level limit, not a tracking one — raising the YOLO inference size to
960 did not separate packed bodies (ADR-0037), it only ran slower.

The lever that *can* separate them is a body model. When enabled (``GROUP_SPLIT="pose"``) this
module runs a second, lightweight model — **YOLOv8-pose** — on frames that contain a suspiciously
*wide* person box, counts the distinct skeletons inside that box, and splits it into one sub-track
per skeleton. Each sub-track then flows through the normal pipeline (size gate -> floor mask ->
motion associator -> Re-ID gallery) as its own foot-point, lifting the count toward the truth.

Design mirrors the VLM / embedder / associator hooks:
  - ``build_splitter`` returns a `NoOpSplitter` unless ``GROUP_SPLIT="pose"`` — so the default
    `docker compose up` (replay, no models) and the offline detect pass are both unaffected unless a
    reviewer opts in. The acceptance gate is never coupled to a second model.
  - The split DECISION (`split_track`) is a **pure** function of box geometry + skeleton positions,
    fully unit-tested. Only the pose inference touches torch, and it is injectable for testing.

Honest limit: on heavy overhead occlusion pose keypoints are themselves unreliable, so this recovers
*some* packed pairs, not all. It is measured and reported, never assumed (cf. ADR-0037).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from shelfsense_common.contracts import BBox

from app.track import Track

# Sub-track ids are minted as parent_id * SUB_STRIDE + slot so a split person gets a stable,
# collision-free id (ByteTrack ids are small ints; <SUB_STRIDE tracks and <SUB_STRIDE slots).
SUB_STRIDE = 1000


@dataclass(frozen=True)
class PosePerson:
    """One pose detection: box centre (inside-box test) + foot-point (where they stand)."""

    cx: float
    cy: float
    foot_x: float
    foot_y: float


class GroupSplitter(Protocol):
    """Turns a frame's tracks into a possibly-longer list, splitting merged-group boxes."""

    def split(self, image: np.ndarray, tracks: list[Track]) -> list[Track]: ...


class NoOpSplitter:
    """Default: no splitting — the tracks pass through unchanged (gate-safe, no model)."""

    def split(self, image: np.ndarray, tracks: list[Track]) -> list[Track]:
        return tracks


def _inside(px: float, py: float, box: BBox) -> bool:
    return box.x <= px <= box.x + box.w and box.y <= py <= box.y + box.h


def split_track(
    track: Track,
    people: list[PosePerson],
    *,
    min_aspect: float,
    min_people: int,
) -> list[Track]:
    """Split one track's box into per-skeleton sub-tracks when it looks like a merged group.

    A box is a *group candidate* only when it is wide relative to its height (`w/h >= min_aspect`):
    a single standing person is tall (ratio well under 1), while two people side-by-side widen the
    merged box. We split only when at least `min_people` pose skeletons actually fall inside the
    box, so a wide-but-single box (a person bending, carrying a bag) is untouched. Sub-tracks are
    ordered left-to-right by foot x, get deterministic ids, and each takes a vertical slice of the
    parent box centred on its skeleton's foot so its `foot_point` lands where that person stands.
    """
    h = track.bbox.h
    if h <= 0 or (track.bbox.w / h) < min_aspect:
        return [track]
    inside = [p for p in people if _inside(p.cx, p.cy, track.bbox)]
    if len(inside) < min_people:
        return [track]
    inside.sort(key=lambda p: p.foot_x)
    n = len(inside)
    sub_w = track.bbox.w / n
    subs: list[Track] = []
    for slot, p in enumerate(inside):
        sub_x = p.foot_x - sub_w / 2.0  # centre the slice on the skeleton's standing point
        subs.append(
            Track(
                track_id=track.track_id * SUB_STRIDE + slot,
                bbox=BBox(x=sub_x, y=track.bbox.y, w=sub_w, h=h),
                confidence=track.confidence,
            )
        )
    return subs


class PoseGroupSplitter:
    """Runs YOLOv8-pose on group-candidate frames and splits merged boxes by skeleton (ADR-0038).

    `detect_people` is injectable (a frame -> list[PosePerson] callable) so `split` is testable
    without torch; left None it lazily loads the pose model. Pose inference is paid for **only**
    when
    a frame actually contains a wide box, bounding the extra cost to crowded frames.
    """

    def __init__(
        self,
        model_path: str,
        *,
        conf: float,
        min_aspect: float,
        min_people: int,
        detect_people=None,
        log=None,
    ) -> None:
        self._model_path = model_path
        self._conf = conf
        self._min_aspect = min_aspect
        self._min_people = min_people
        self._detect_people = detect_people
        self._log = log
        self._model = None  # lazy

    def _is_candidate(self, track: Track) -> bool:
        return track.bbox.h > 0 and (track.bbox.w / track.bbox.h) >= self._min_aspect

    def _people(self, image: np.ndarray) -> list[PosePerson]:
        if self._detect_people is not None:
            return self._detect_people(image)
        from ultralytics import YOLO  # lazy: heavy import (torch), not needed in unit tests

        if self._model is None:
            self._model = YOLO(self._model_path)
        results = self._model.predict(image, conf=self._conf, verbose=False)
        people: list[PosePerson] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            kpts = getattr(result, "keypoints", None)
            kdata = kpts.data if kpts is not None and kpts.data is not None else None
            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                foot_x, foot_y = cx, y2
                # Refine the foot from the ankle keypoints (COCO idx 15/16) when confident.
                if kdata is not None and i < len(kdata):
                    ankles = [kdata[i][j] for j in (15, 16) if float(kdata[i][j][2]) > 0.3]
                    if ankles:
                        foot_x = sum(float(a[0]) for a in ankles) / len(ankles)
                        foot_y = max(float(a[1]) for a in ankles)
                people.append(PosePerson(cx, cy, foot_x, foot_y))
        return people

    def split(self, image: np.ndarray, tracks: list[Track]) -> list[Track]:
        if not any(self._is_candidate(t) for t in tracks):
            return tracks  # no wide boxes this frame -> skip pose inference entirely
        people = self._people(image)
        out: list[Track] = []
        for t in tracks:
            out.extend(
                split_track(t, people, min_aspect=self._min_aspect, min_people=self._min_people)
            )
        return out


def build_splitter(settings, log=None) -> GroupSplitter:
    """Construct the pose splitter, or the no-op pass-through (the default, gate-safe path).

    Returns `NoOpSplitter` unless ``GROUP_SPLIT`` == "pose", so onboarding the second model is an
    explicit opt-in for the offline detection pass — the replay gate never loads it.
    """
    if settings.group_split.lower() != "pose":
        return NoOpSplitter()
    return PoseGroupSplitter(
        settings.group_split_pose_model,
        conf=settings.group_split_pose_conf,
        min_aspect=settings.group_split_min_aspect,
        min_people=settings.group_split_min_people,
        log=log,
    )
