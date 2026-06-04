# PROMPT
# Task:
#   - Unit-test the lightweight Re-ID matching: signature distance + the ReIDGallery decisions.
# Context:
#   - signature_distance is cosine distance on L2-normalised signatures (0 = identical). ReIDGallery
#     matches a new signature to the nearest known visitor within max_distance (merge -> same id),
#     else mints a new id. A re-matched visitor seen after reentry_min_gap is flagged is_reentry.
#     (ADR-0008: appearance Re-ID for cross-camera dedup.)
# Constraints:
#   - Pure logic only — feed signatures as plain numpy vectors; inject a deterministic id_factory.
# Output:
#   - Tests: distance identical=0 / orthogonal=1; new signature mints; a near signature merges to
#     the same id; a far signature mints a new id; a re-match after the gap is flagged is_reentry.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the appearance Re-ID matching logic."""

import itertools

import numpy as np
from app.reid import ReIDGallery, signature_distance


def _ids():
    seq = itertools.count()
    return lambda: f"VIS_{next(seq)}"


def _norm(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


SIG_A = _norm([1.0, 0.0, 0.0])
SIG_A_NEAR = _norm([0.95, 0.05, 0.0])  # cosine distance to A ~0.001 (well within threshold)
SIG_B = _norm([0.0, 1.0, 0.0])  # orthogonal to A -> distance 1.0


def test_distance_identical_and_orthogonal():
    assert signature_distance(SIG_A, SIG_A) == 0.0
    assert abs(signature_distance(SIG_A, SIG_B) - 1.0) < 1e-6


def test_first_signature_mints_new_visitor():
    g = ReIDGallery(max_distance=0.35, id_factory=_ids())
    res = g.resolve(SIG_A, ts_ms=0)
    assert res.is_new and not res.is_reentry and res.visitor_id == "VIS_0"


def test_near_signature_merges_to_same_visitor():
    g = ReIDGallery(max_distance=0.35, id_factory=_ids())
    first = g.resolve(SIG_A, ts_ms=0)
    again = g.resolve(SIG_A_NEAR, ts_ms=1000)  # close + recent -> same visitor, not a reentry
    assert again.visitor_id == first.visitor_id
    assert not again.is_new and not again.is_reentry
    assert g.unique_count == 1


def test_far_signature_mints_distinct_visitor():
    g = ReIDGallery(max_distance=0.35, id_factory=_ids())
    a = g.resolve(SIG_A, ts_ms=0)
    b = g.resolve(SIG_B, ts_ms=0)  # orthogonal -> distance 1.0 > 0.35 -> new
    assert a.visitor_id != b.visitor_id
    assert b.is_new and g.unique_count == 2


def test_rematch_after_gap_is_reentry():
    g = ReIDGallery(max_distance=0.35, reentry_min_gap_ms=5000, id_factory=_ids())
    g.resolve(SIG_A, ts_ms=0)
    res = g.resolve(SIG_A, ts_ms=10000)  # same person, 10s later (> 5s gap) -> REENTRY
    assert not res.is_new and res.is_reentry
    assert g.unique_count == 1
