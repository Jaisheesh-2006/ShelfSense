# PROMPT
# Task:
#   - Unit-test the calibrated CAM3 entrance-line geometry.
# Context:
#   - EntranceLine.side()/is_inside() classify a point as inside (wood retail floor) or outside
#     (dark threshold/mall) from the sign of a cross-product vs inside_sign.
# Constraints:
#   - Read coordinates from the live STORE config (do not hardcode) so tests track re-calibration.
# Output:
#   - Tests: CAM3 is the calibrated entrance; interior point inside, exterior point outside;
#     side() signed and consistent with inside_sign; a point exactly on the line returns 0.
# CHANGES MADE:
#   - Switched from hardcoded coordinates to the live STORE config.
#   - Added the on-the-line (==0) boundary case.
"""Unit tests for the calibrated entrance line geometry (inside vs outside)."""
from shelfsense_common.contracts import STORE, EntranceLine


def test_entrance_camera_is_calibrated():
    cam = STORE.entrance_camera
    assert cam is not None and cam.camera_id == "CAM3"
    assert cam.entrance_line is not None
    assert cam.entrance_line.calibrated is True


def test_inside_outside_match_the_store_geometry():
    line = STORE.entrance_camera.entrance_line
    # Upper part of the frame (smaller y) = toward the product floor = inside the store.
    assert line.is_inside(640, 250) is True
    # Lower part (larger y) = toward the mall threshold = outside.
    assert line.is_inside(1000, 800) is False


def test_side_is_signed_and_consistent_with_inside_sign():
    line = STORE.entrance_camera.entrance_line
    assert line.side(640, 250) == line.inside_sign
    assert line.side(1000, 800) == -line.inside_sign


def test_point_exactly_on_line_returns_zero():
    line = EntranceLine(x1=0, y1=0, x2=10, y2=0)
    assert line.side(5, 0) == 0
    assert line.side(5, -3) in (-1, 1)
