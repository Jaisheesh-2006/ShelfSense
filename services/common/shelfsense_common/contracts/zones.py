"""Store + camera + zone configuration, derived from the real floor plan.

Source of truth: docs/wiki/GROUND_TRUTH.md §1 (camera map) and §4 (floor plan). Zones are the
store's actual zones, not hand-drawn guesses (see DECISIONS ADR-0004 / PD-4). For v1 we use
*camera-level* zone assignment: each camera maps to one primary zone. The `entrance_line` on the
entrance camera defines the footfall counting line (pixel coords, to be calibrated on a CAM 3
frame in Phase 2 — defaults below are placeholders flagged as such).
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ZoneName(StrEnum):
    ENTRANCE = "entrance"
    SKINCARE_AISLE = "skincare_aisle"
    MAKEUP_AISLE = "makeup_aisle"
    FOH_CENTER = "foh_center"
    CHECKOUT = "checkout"
    ACCESSORIES = "accessories"
    STOCKROOM = "stockroom"


class CameraRole(StrEnum):
    ENTRANCE = "entrance"
    PRODUCT = "product"
    CHECKOUT = "checkout"
    STOCKROOM = "stockroom"


class EntranceLine(BaseModel):
    """A virtual line for entry/exit counting, in pixel coords (1920x1080 frame).

    Crossing from the outside side to the inside counts as an entry. `inside_sign` records which
    side of the line (per `side()`) is the store interior, so the tracker can tell an entry from
    an exit. `calibrated=False` means the coordinates are a placeholder pending visual calibration.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    inside_sign: int = 1
    calibrated: bool = False

    def side(self, px: float, py: float) -> int:
        """Return which side of the line a point is on: +1, -1, or 0 (on the line).

        Uses the sign of the 2D cross product of the line direction and the point offset.
        """
        cross = (self.x2 - self.x1) * (py - self.y1) - (self.y2 - self.y1) * (px - self.x1)
        if cross > 0:
            return 1
        if cross < 0:
            return -1
        return 0

    def is_inside(self, px: float, py: float) -> bool:
        """True if the point lies on the store-interior side of the line."""
        return self.side(px, py) == self.inside_sign


class CameraConfig(BaseModel):
    camera_id: str
    file: str
    role: CameraRole
    primary_zone: ZoneName
    fps: float
    # Whether detections here count as customers. Stockroom = staff-only, excluded from footfall.
    is_customer_area: bool = True
    entrance_line: EntranceLine | None = None


class StoreConfig(BaseModel):
    store_id: str
    store_name: str
    cameras: list[CameraConfig] = Field(default_factory=list)

    def camera(self, camera_id: str) -> CameraConfig | None:
        return next((c for c in self.cameras if c.camera_id == camera_id), None)

    @property
    def entrance_camera(self) -> CameraConfig | None:
        return next((c for c in self.cameras if c.role is CameraRole.ENTRANCE), None)


# Canonical store config for Brigade_Bangalore (ST1008), matching the "Current" floor plan.
STORE = StoreConfig(
    store_id="ST1008",
    store_name="Brigade_Bangalore",
    cameras=[
        CameraConfig(
            camera_id="CAM1",
            file="CAM 1.mp4",
            role=CameraRole.PRODUCT,
            primary_zone=ZoneName.SKINCARE_AISLE,
            fps=29.97,
        ),
        CameraConfig(
            camera_id="CAM2",
            file="CAM 2.mp4",
            role=CameraRole.PRODUCT,
            primary_zone=ZoneName.MAKEUP_AISLE,
            fps=29.97,
        ),
        CameraConfig(
            camera_id="CAM3",
            file="CAM 3.mp4",
            role=CameraRole.ENTRANCE,
            primary_zone=ZoneName.ENTRANCE,
            fps=29.97,
            # Entrance line along the front edge of the retail wood floor, by the centre glass
            # partition where the real doorway is (user-confirmed). NOTE: an earlier Slice 2.2
            # attempt moved this onto the RIGHT-side corridor chasing heavy foot traffic there —
            # but that corridor is the MALL walkway (pass-by, not store entries), so it was
            # reverted (ADR-0006). Real store entries cross here, centre-left; the dense right-side
            # motion must NOT be counted as footfall. inside_sign=-1 → the wood-floor side is
            # inside. See GROUND_TRUTH §1.
            entrance_line=EntranceLine(
                x1=320, y1=490, x2=1140, y2=415, inside_sign=-1, calibrated=True
            ),
        ),
        CameraConfig(
            camera_id="CAM4",
            file="CAM 4.mp4",
            role=CameraRole.STOCKROOM,
            primary_zone=ZoneName.STOCKROOM,
            fps=24.98,
            is_customer_area=False,
        ),
        CameraConfig(
            camera_id="CAM5",
            file="CAM 5.mp4",
            role=CameraRole.CHECKOUT,
            primary_zone=ZoneName.CHECKOUT,
            fps=24.98,
        ),
    ],
)
