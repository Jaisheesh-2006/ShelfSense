# PROMPT
# Task:
#   - Unit-test the gallery-backed VisitorRegistry that resolves per-camera tracks to GLOBAL ids.
# Context:
#   - Slice 2.4: a visitor_id is the de-duplicated identity. The registry caches (camera, track)->id
#     and delegates first-time resolution to the ReIDGallery by appearance signature, so the same
#     person on two cameras collapses to one id. session_seq is one increasing ordinal per visitor.
# Constraints:
#   - Pure logic; build a gallery with a deterministic id_factory and feed signatures as np vectors.
# Output:
#   - Tests: same (camera,track) is cached (one resolve); matching signatures on different cameras
#     -> same global id (dedup); distinct signatures -> distinct ids; session_seq per visitor;
#     is_resolved flips after first resolve.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the gallery-backed VisitorRegistry."""

import itertools

import numpy as np
from app.reid import ReIDGallery
from app.visits import VisitorRegistry


def _registry():
    seq = itertools.count()
    gallery = ReIDGallery(max_distance=0.35, id_factory=lambda: f"VIS_{next(seq)}")
    return VisitorRegistry(gallery)


def _norm(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


SIG_A = _norm([1.0, 0.0, 0.0])
SIG_B = _norm([0.0, 1.0, 0.0])


def test_same_camera_track_is_cached():
    reg = _registry()
    first = reg.resolve("CAM1", 7, SIG_A, ts_ms=0)
    assert not reg.is_resolved("CAM1", 8)
    assert reg.is_resolved("CAM1", 7)
    again = reg.resolve("CAM1", 7, SIG_B, ts_ms=999)  # cached: signature ignored, same id
    assert again.visitor_id == first.visitor_id


def test_same_person_across_cameras_dedupes_to_one_id():
    reg = _registry()
    cam1 = reg.resolve("CAM1", 1, SIG_A, ts_ms=0)
    cam2 = reg.resolve("CAM2", 9, SIG_A, ts_ms=4000)  # different camera+track, same appearance
    assert cam1.visitor_id == cam2.visitor_id  # de-duplicated
    assert reg.unique_count == 1


def test_distinct_appearances_are_distinct_visitors():
    reg = _registry()
    a = reg.resolve("CAM1", 1, SIG_A, ts_ms=0)
    b = reg.resolve("CAM2", 1, SIG_B, ts_ms=0)
    assert a.visitor_id != b.visitor_id
    assert reg.unique_count == 2


def test_session_seq_increments_per_visitor():
    reg = _registry()
    vid = reg.resolve("CAM1", 1, SIG_A, ts_ms=0).visitor_id
    assert reg.next_seq(vid) == 1
    assert reg.next_seq(vid) == 2
    other = reg.resolve("CAM2", 2, SIG_B, ts_ms=0).visitor_id
    assert reg.next_seq(other) == 1  # independent per visitor
