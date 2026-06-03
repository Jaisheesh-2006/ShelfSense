"""Store config — Store_2 (ST1009), the second store from the corrected dataset.

Clips: `Store_CCTV_Clips/Store_2/Store 2/` — `entry 1`, `entry 2`, `zone`, `billing_area`, all
**960x1080 @ 25fps**. We assigned the id **ST1009** (the data has no id of its own; ADR-0026).

Calibration note (DESIGN A14): Store_2 has **no POS**, and its clips were recorded on **different
real days** (entry 1: 29-Mar, entry 2: 08-Mar) — per the user's direction we treat them as **one
synthetic day** (`clip_start_iso` below). The two entrances open onto the mall corridor (pass-by
hazard, as ST1008's CAM3); the entrance lines are now **calibrated** from grid-overlaid frames
(wood-floor side = interior). **User-provided ground truth: 22 customers + 3 staff** — the crowd
tuning below is calibrated to it. Zone labels are defaults, refined by the VLM (ADR-0027) when
enabled. Conversion is **N/A** for ST1009 (no sales).
"""

from __future__ import annotations

from shelfsense_common.contracts.zones import (
    CameraConfig,
    CameraRole,
    EntranceLine,
    StoreConfig,
    ZoneName,
)

STORE_CONFIG = StoreConfig(
    store_id="ST1009",
    store_name="Store_2",
    clips_dir="Store_2/Store 2",
    # All four clips normalised to ONE synthetic day (their real dates differ). Same calendar day as
    # ST1008 so both stores fall in the same query window; ~13:30 IST matches the entry-2 overlay.
    clip_start_iso="2026-04-10T13:30:00+05:30",
    # Crowd tuning (ADR-0030): Store_2 is BUSY (~22 customers vs Store_1's 2), so it needs a
    # stricter Re-ID distance (less over-merging) and a shorter dwell than the global defaults.
    # Calibrated to the ground truth (22+3): a sweep gave 0.55->6, 0.35->20, 0.30->23, 0.25->37
    # unique; 0.30 + 800ms lands at ~23 (~25). Store_1 keeps the global 0.55/2000 (its own truth).
    reid_max_distance=0.33,
    min_zone_dwell_ms=800,
    staff_uniform_hint="Store staff wear pink shirts; shoppers are in mixed casual colors.",
    cameras=[
        CameraConfig(
            camera_id="ENTRY1",
            file="entry 1.mp4",
            role=CameraRole.ENTRANCE,
            primary_zone=ZoneName.ENTRANCE,
            fps=25.0,
            # Calibrated on a grid-overlaid frame: the white strip in front of the wood floor is
            # OUTSIDE. The entrance line sits on the wood edge so only true interior foot-points
            # count; the tiled/white mall area above is pass-by.
            entrance_line=EntranceLine(
                x1=140, y1=535, x2=760, y2=495, inside_sign=1, calibrated=True
            ),
        ),
        CameraConfig(
            camera_id="ENTRY2",
            file="entry 2.mp4",
            role=CameraRole.ENTRANCE,
            primary_zone=ZoneName.ENTRANCE,
            fps=25.0,
            # Calibrated: white strip is outside; line sits on the wood edge (interior below).
            entrance_line=EntranceLine(
                x1=150, y1=560, x2=740, y2=500, inside_sign=1, calibrated=True
            ),
        ),
        CameraConfig(
            camera_id="ZONE",
            file="zone.mp4",
            role=CameraRole.PRODUCT,
            primary_zone=ZoneName.MAKEUP_AISLE,  # default; VLM relabels from the shelves (ADR-0027)
            fps=25.0,
        ),
        CameraConfig(
            camera_id="BILLING",
            file="billing_area.mp4",
            role=CameraRole.CHECKOUT,
            primary_zone=ZoneName.CHECKOUT,
            fps=25.0,
            # No floor mask calibrated for Store_2 yet → fails open (all foot-points accepted).
        ),
    ],
)
