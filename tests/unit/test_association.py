# PROMPT
# Task:
#   - Unit-test the pluggable tracking-based track association (ADR-0037): the MotionTrackAssociator
#     stitches fragmented per-camera ByteTrack ids into one stable local id by motion, and the
#     IdentityAssociator (legacy fallback) passes ids straight through.
# Context:
#   - On overhead CCTV appearance Re-ID over-splits one person front/back (ADR-0036). Motion is the
#     reliable cue: a track that dies at P/time T and a new track born near P shortly after is the
#     SAME person. MotionTrackAssociator gates on a (min_gap, max_gap] absence window + a
#     constant-velocity predicted-position jump. The min_gap guard must stop a still-live track
#     being stolen by another person in the same frame. build_associator picks strategy from config.
# Constraints:
#   - Pure logic only — feed positions/timestamps as plain numbers; no OpenCV / torch / video.
# Output:
#   - Tests: identity pass-through; mint + reuse; velocity-predicted stitch; far jump -> new; long
#     gap -> new; a near-but-still-live track is NOT stolen (coexistence); factory selection.
"""Unit tests for spatio-temporal tracklet stitching (track association)."""

from __future__ import annotations

from types import SimpleNamespace

from app.association import (
    IdentityAssociator,
    MotionTrackAssociator,
    build_associator,
)


def _motion() -> MotionTrackAssociator:
    # Explicit gates so the arithmetic in each test is deterministic (not frame-rate derived).
    return MotionTrackAssociator(max_gap_ms=2000, min_gap_ms=150, max_jump_px=100)


def test_identity_associator_passes_raw_id_through():
    a = IdentityAssociator()
    assert a.assign(7, 10.0, 20.0, 0) == 7
    assert a.assign(7, 99.0, 99.0, 5000) == 7  # never remaps — legacy appearance-only path


def test_motion_mints_then_reuses_same_raw_id():
    a = _motion()
    first = a.assign(1, 100.0, 100.0, 0)
    again = a.assign(1, 110.0, 100.0, 100)  # same raw id keeps its local id
    assert first == again


def test_velocity_predicted_fragment_stitches_to_same_local():
    a = _motion()
    local = a.assign(1, 100.0, 100.0, 0)
    a.assign(1, 110.0, 100.0, 100)  # moving right ~0.05 px/ms
    # raw 1 dies; a NEW raw id 2 appears 300ms later near the predicted spot (110 + 0.05*300 = 125).
    stitched = a.assign(2, 120.0, 100.0, 400)
    assert stitched == local  # motion re-links it without any appearance signal


def test_far_new_track_mints_a_distinct_local():
    a = _motion()
    local = a.assign(1, 100.0, 100.0, 0)
    a.assign(1, 100.0, 100.0, 100)  # stationary → ~zero velocity
    far = a.assign(2, 400.0, 100.0, 400)  # 300px away, within the time gate but past the jump gate
    assert far != local


def test_gap_beyond_max_is_a_new_local():
    a = _motion()
    local = a.assign(1, 100.0, 100.0, 0)
    later = a.assign(2, 100.0, 100.0, 5000)  # same spot but 5s later (> max_gap) → not the same id
    assert later != local


def test_still_live_track_is_not_stolen_by_a_coexisting_person():
    # Two people on screen at once; a third detection near the first must NOT inherit its id while
    # that first track is still alive (sub-frame gap) — the min_gap guard protects coexistence.
    a = _motion()
    l1 = a.assign(1, 100.0, 100.0, 0)
    l2 = a.assign(2, 500.0, 500.0, 0)
    a.assign(1, 105.0, 100.0, 100)
    a.assign(2, 500.0, 500.0, 100)
    # New raw id 3 appears at ts=200 NEAR track 1, before track 1 advances this frame (100ms gap).
    l3 = a.assign(3, 110.0, 100.0, 200)
    assert l3 != l1 and l3 != l2  # distinct identities preserved


def test_build_associator_selects_strategy_and_scales_gates():
    base = SimpleNamespace(
        tracker_sample_fps=5.0,  # 200ms frame interval → min_gap floor = 1.5 * 200 = 300ms
        stitch_min_gap_ms=150,
        stitch_max_gap_ms=2000,
        stitch_max_jump_frac=0.10,
    )
    appearance = build_associator(
        SimpleNamespace(track_association="appearance", **vars(base)), 960, 1080
    )
    assert isinstance(appearance, IdentityAssociator)

    motion = build_associator(SimpleNamespace(track_association="motion", **vars(base)), 960, 1080)
    assert isinstance(motion, MotionTrackAssociator)
    assert motion._min_gap_ms == 300.0  # lifted above one sampled-frame interval
    assert motion._max_jump_px == 0.10 * 1080  # fraction of the frame's longest side
