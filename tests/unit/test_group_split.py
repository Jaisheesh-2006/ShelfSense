# PROMPT
# Task:
#   - Unit-test the pluggable pose group-splitter (ADR-0038): split_track breaks a merged-group box
#     into one sub-track per skeleton; PoseGroupSplitter runs pose inference only on frames with a
#     wide box; build_splitter selects NoOpSplitter (default) vs PoseGroupSplitter from config.
# Context:
#   - YOLO boxes 2-4 packed shoppers as ONE track on overhead views, deflating the unique count. We
#     split a box ONLY when it is wide (w/h >= min_aspect — a lone standing person is tall) AND at
#     least min_people skeletons fall inside it. Sub-tracks are ordered left-to-right by foot x, get
#     deterministic ids (parent*SUB_STRIDE + slot), and each takes a slice centred on its foot so
#     its foot_point lands where they stand. Pose inference is injectable (torch-free split).
# Constraints:
#   - Pure logic only — feed boxes + synthetic skeletons as plain numbers; no ultralytics / torch.
# Output:
#   - Tests: tall box not split; wide box + 2 inside -> 2 ordered sub-tracks (ids/boxes/feet);
#     wide box + 1 inside -> unchanged; skeletons outside ignored; no wide box -> pose NOT called;
#     wide box -> pose called + split; factory selection (none -> NoOp, pose -> PoseGroupSplitter).
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for pose-based group splitting (ADR-0038)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from app.group_split import (
    SUB_STRIDE,
    NoOpSplitter,
    PoseGroupSplitter,
    PosePerson,
    build_splitter,
)
from app.track import Track
from shelfsense_common.contracts import BBox


def _track(track_id: int, x: float, y: float, w: float, h: float, conf: float = 0.9) -> Track:
    return Track(track_id=track_id, bbox=BBox(x=x, y=y, w=w, h=h), confidence=conf)


def _settings(**over) -> SimpleNamespace:
    base = {
        "group_split": "pose",
        "group_split_pose_model": "yolov8n-pose.pt",
        "group_split_pose_conf": 0.25,
        "group_split_min_aspect": 0.85,
        "group_split_min_people": 2,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_split_track_leaves_tall_single_box_untouched():
    # A lone standing person is TALL (w/h = 0.4 < min_aspect) — never a group candidate, even if two
    # stray skeletons happen to fall inside the box.
    track = _track(5, x=0, y=0, w=40, h=100)
    people = [PosePerson(10, 50, 10, 100), PosePerson(30, 50, 30, 100)]
    out = _split(track, people)
    assert out == [track]


def test_split_track_splits_wide_box_with_two_skeletons():
    track = _track(7, x=0, y=0, w=200, h=100)  # w/h = 2.0 -> candidate
    # Given out of order; the splitter must order left-to-right by foot x.
    people = [PosePerson(150, 50, 150, 100), PosePerson(50, 50, 50, 100)]
    out = _split(track, people)
    assert len(out) == 2
    # Deterministic, collision-free ids by slot.
    assert [t.track_id for t in out] == [7 * SUB_STRIDE + 0, 7 * SUB_STRIDE + 1]
    # Each sub-box is a half-width slice centred on its skeleton's foot (foot_point = that foot).
    assert out[0].bbox.w == 100 and out[1].bbox.w == 100
    assert out[0].foot_point == (50, 100)
    assert out[1].foot_point == (150, 100)
    assert all(t.confidence == track.confidence for t in out)


def test_split_track_keeps_wide_box_with_single_person():
    # Wide box but only one skeleton inside (someone bending / carrying a bag) -> not a group.
    track = _track(3, x=0, y=0, w=200, h=100)
    out = _split(track, [PosePerson(100, 50, 100, 100)])
    assert out == [track]


def test_split_track_ignores_skeletons_outside_the_box():
    track = _track(9, x=0, y=0, w=200, h=100)
    inside = PosePerson(100, 50, 100, 100)
    outside = PosePerson(500, 50, 500, 100)  # cx outside the box
    out = _split(track, [inside, outside])
    assert out == [track]  # only one inside -> below min_people, unchanged


def test_pose_splitter_skips_inference_when_no_wide_box():
    calls = {"n": 0}

    def detector(_img):
        calls["n"] += 1
        return [PosePerson(10, 50, 10, 100), PosePerson(30, 50, 30, 100)]

    splitter = PoseGroupSplitter(
        "m", conf=0.25, min_aspect=0.85, min_people=2, detect_people=detector
    )
    tall = [_track(1, 0, 0, 40, 100), _track(2, 100, 0, 30, 90)]
    out = splitter.split(np.zeros((10, 10, 3), dtype=np.uint8), tall)
    assert out == tall  # unchanged
    assert calls["n"] == 0  # pose model never run — no candidate box this frame


def test_pose_splitter_runs_inference_and_splits_candidate():
    def detector(_img):
        return [PosePerson(50, 50, 50, 100), PosePerson(150, 50, 150, 100)]

    splitter = PoseGroupSplitter(
        "m", conf=0.25, min_aspect=0.85, min_people=2, detect_people=detector
    )
    wide = [_track(7, 0, 0, 200, 100)]
    out = splitter.split(np.zeros((10, 10, 3), dtype=np.uint8), wide)
    assert len(out) == 2
    assert [t.track_id for t in out] == [7 * SUB_STRIDE, 7 * SUB_STRIDE + 1]


def test_build_splitter_selects_strategy_from_config():
    assert isinstance(build_splitter(_settings(group_split="none")), NoOpSplitter)
    assert isinstance(build_splitter(_settings(group_split="POSE")), PoseGroupSplitter)
    # NoOp passes tracks straight through.
    tracks = [_track(1, 0, 0, 200, 100)]
    assert NoOpSplitter().split(np.zeros((4, 4, 3), dtype=np.uint8), tracks) == tracks


def _split(track: Track, people: list[PosePerson]) -> list[Track]:
    from app.group_split import split_track

    return split_track(track, people, min_aspect=0.85, min_people=2)
