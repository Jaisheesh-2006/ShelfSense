# PROMPT
# Task:
#   - Unit-test the calibrated CAM3 entrance-line geometry.
# Context:
#   - EntranceLine.side()/is_inside() classify a point as inside (wood retail floor) or outside
#     (dark threshold/mall) from the sign of a cross-product vs inside_sign.
# Constraints:
#   - Read coordinates from the live ST1008 store config (do not hardcode) so tests track
#     re-calibration. The config now comes from the pluggable registry (ADR-0028).
# Output:
#   - Tests: CAM3 is the calibrated entrance; interior point inside, exterior point outside;
#     side() signed and consistent with inside_sign; a point exactly on the line returns 0.
#   - FloorRegion: CAM5 has a calibrated floor; a floor foot-point is inside, a back-doorway/
#     display foot-point is outside; a degenerate (<3 vertex) region fails open.
# CHANGES MADE:
#   - Switched from hardcoded coordinates to the live store config.
#   - Now reads ST1008 from the store registry (`get_store`) instead of the removed `STORE` const.
#   - Added the on-the-line (==0) boundary case.
#   - Added FloorRegion (CAM5 mirror/display mask) tests (Slice 2.4b).
"""Unit tests for the calibrated entrance line + CAM5 floor-mask geometry."""

from shelfsense_common.contracts import EntranceLine, FloorRegion
from shelfsense_common.stores import get_store

STORE = get_store("ST1008")


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


def test_cam5_has_calibrated_floor_region():
    cam = STORE.camera("CAM5")
    assert cam is not None and cam.floor_region is not None
    assert cam.floor_region.calibrated is True


def test_floor_region_keeps_floor_drops_back_and_display():
    floor = STORE.camera("CAM5").floor_region
    # A foot-point where the staff actually stand on the wood floor (centre, lower frame) is inside.
    assert floor.contains(900, 850) is True
    # The back doorway (top-centre, where phantom tracks had foot-point y~220) is masked out.
    assert floor.contains(1016, 220) is False
    # The backlit accessories / mirror band (far right) is masked out.
    assert floor.contains(1700, 300) is False


def test_floor_region_simple_square():
    sq = FloorRegion(vertices=[(0, 0), (10, 0), (10, 10), (0, 10)])
    assert sq.contains(5, 5) is True
    assert sq.contains(15, 5) is False


def test_degenerate_region_fails_open():
    # Fewer than 3 vertices can't bound an area; constrain nothing rather than drop everything.
    assert FloorRegion(vertices=[(0, 0), (1, 1)]).contains(5, 5) is True
