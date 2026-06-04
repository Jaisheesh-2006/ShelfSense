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


# Rich zone descriptors mirroring the delivered `sample_events.jsonl` (ADR-0040):
# each canonical zone_id -> (zone_name, zone_type, is_revenue_zone). Derived deterministically from
# the store's real zones (GROUND_TRUTH §4), never fabricated. These populate EventMetadata's
# superset zone fields without changing the flat top-level schema.
_ZONE_DESCRIPTORS: dict[str, tuple[str, str, bool]] = {
    ZoneName.ENTRANCE: ("Entrance", "ENTRANCE", False),
    ZoneName.SKINCARE_AISLE: ("Skincare Aisle", "SHELF", True),
    ZoneName.MAKEUP_AISLE: ("Makeup Aisle", "SHELF", True),
    ZoneName.FOH_CENTER: ("Front of House", "DISPLAY", True),
    ZoneName.CHECKOUT: ("Billing Counter Queue", "BILLING", True),
    ZoneName.ACCESSORIES: ("Accessories", "SHELF", True),
    ZoneName.STOCKROOM: ("Stockroom", "BACK_OF_HOUSE", False),
}


def zone_descriptor(zone_id: str | None) -> tuple[str | None, str | None, bool | None]:
    """Return (zone_name, zone_type, is_revenue_zone) for a zone_id (ADR-0040).

    Returns (None, None, None) for a null zone (ENTRY/EXIT carry no zone). Unknown zone_ids fall
    back to a title-cased name + SHELF/revenue=True, so adding a store needs no change here.
    """
    if zone_id is None:
        return None, None, None
    descriptor = _ZONE_DESCRIPTORS.get(zone_id)
    if descriptor is not None:
        return descriptor
    return zone_id.replace("_", " ").title(), "SHELF", True


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


class FloorRegion(BaseModel):
    """The walkable floor as a pixel polygon — detections whose foot-point falls OUTSIDE it are
    ignored (Slice 2.4b). This suppresses physically-impossible detections: mirror reflections and
    backlit product displays / wall posters, whose apparent "feet" land on a wall, not the floor.
    A general, calibrated mask (cf. the entrance line); `calibrated=False` flags placeholder coords.
    """

    vertices: list[tuple[float, float]]  # ordered polygon, pixel coords (1920x1080 frame)
    calibrated: bool = False

    def contains(self, px: float, py: float) -> bool:
        """Point-in-polygon by ray casting (odd crossings = inside). Pure, no deps."""
        verts = self.vertices
        n = len(verts)
        if n < 3:
            return True  # a degenerate region constrains nothing (fail open)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = verts[i]
            xj, yj = verts[j]
            intersects = (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi
            if intersects:
                inside = not inside
            j = i
        return inside


class CameraConfig(BaseModel):
    camera_id: str
    file: str
    role: CameraRole
    primary_zone: ZoneName
    fps: float
    # Whether detections here count as customers. Stockroom = staff-only, excluded from footfall.
    is_customer_area: bool = True
    entrance_line: EntranceLine | None = None
    # Optional walkable-floor mask: foot-points outside it are dropped (reflections/displays).
    floor_region: FloorRegion | None = None


class StoreConfig(BaseModel):
    store_id: str
    store_name: str
    cameras: list[CameraConfig] = Field(default_factory=list)
    # Where this store's clips live, RELATIVE to the detector's CCTV mount (`CCTV_DIR`). One mount
    # holds every store; each store points at its own subfolder, so a store needs no new mount.
    clips_dir: str = ""
    # Store-local wall-clock start of the clips (ISO-8601). A store's clips are treated as one
    # synchronised window starting here, turning per-frame media time into absolute UTC timestamps.
    # None → fall back to the global `CLIP_START_ISO`. For stores whose real clips span different
    # days (e.g. Store_2), this pins them to ONE synthetic day so daily metrics read sensibly.
    clip_start_iso: str | None = None
    # Optional store-specific staff-uniform hint for the VLM (e.g., "staff wear pink shirts").
    staff_uniform_hint: str | None = None
    # Per-store density tuning (None → global Settings default). A busy store needs a STRICTER Re-ID
    # distance (less merging) + a SHORTER dwell than a quiet one; per-store keeps one store's
    # calibration from disturbing another's (ADR-0030).
    reid_max_distance: float | None = None
    min_zone_dwell_ms: int | None = None
    detector_imgsz: int | None = None
    staff_heuristic_color: str | None = "black"  # e.g., "black", "pink", or None to disable

    def camera(self, camera_id: str) -> CameraConfig | None:
        return next((c for c in self.cameras if c.camera_id == camera_id), None)

    @property
    def entrance_camera(self) -> CameraConfig | None:
        return next((c for c in self.cameras if c.role is CameraRole.ENTRANCE), None)

    @property
    def customer_cameras(self) -> list[CameraConfig]:
        """Cameras whose detections count as customers (excludes staff-only areas)."""
        return [c for c in self.cameras if c.is_customer_area]


# NOTE: concrete store configs live in the pluggable `shelfsense_common.stores` package (one file
# per store, auto-discovered) — NOT here. This module defines only the *models* (ADR-0028). To add a
# store, drop a `stores/<id>.py` exposing `STORE_CONFIG = StoreConfig(...)`; nothing here changes.
