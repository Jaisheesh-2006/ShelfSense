# PROMPT
# Task:
#   - Unit-test the box-size quality gate (ADR-0029) used to drop tiny far/reflection detections so
#     only solid tracks count toward unique visitors.
# Context:
#   - box_area_fraction = bbox area / frame area; passes_size_gate compares it to a min fraction,
#     and a min_frac <= 0 disables the gate. The on-floor (FloorRegion) and pass-by (EntranceLine)
#     gates are tested in test_zones; this covers the size piece.
# Constraints:
#   - Pure arithmetic; no OpenCV, no model. Deterministic.
# Output:
#   - Tests: fraction for a full / half / zero box; empty frame → 0; gate disabled when min_frac<=0;
#     gate passes a large box and rejects a tiny one at a realistic threshold.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the detection-quality size gate."""

from __future__ import annotations

from app.gating import box_area_fraction, passes_size_gate


def test_box_area_fraction_basic():
    assert box_area_fraction(100, 100, 100, 100) == 1.0  # box fills the frame
    assert box_area_fraction(50, 50, 100, 100) == 0.25  # quarter of the frame
    assert box_area_fraction(0, 50, 100, 100) == 0.0  # zero-width box


def test_box_area_fraction_empty_frame_is_zero():
    assert box_area_fraction(10, 10, 0, 0) == 0.0


def test_size_gate_disabled_passes_everything():
    assert passes_size_gate(1, 1, 1920, 1080, 0.0) is True  # min_frac<=0 disables the gate
    assert passes_size_gate(1, 1, 1920, 1080, -1.0) is True


def test_size_gate_rejects_tiny_keeps_large():
    fw, fh, min_frac = 1920, 1080, 0.0015
    # A close shopper (~200x500) is well above the floor; a far blob (~30x60) is well below.
    assert passes_size_gate(200, 500, fw, fh, min_frac) is True
    assert passes_size_gate(30, 60, fw, fh, min_frac) is False
