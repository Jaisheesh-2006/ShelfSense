"""Store config — Brigade_Bangalore (ST1008), the POS/conversion store.

Calibrated against the real CCTV (1920x1080). Clip filenames + folder match the corrected dataset
(`Store_CCTV_Clips/Store_1/Store 1/`). Rationale for each calibrated coordinate is preserved inline
(and in DESIGN A6–A8 / DECISIONS ADR-0006/0010/0011). CAM4 (stockroom) was dropped from the
corrected dataset; the four customer cameras remain.
"""

from __future__ import annotations

from shelfsense_common.contracts.zones import (
    CameraConfig,
    CameraRole,
    EntranceLine,
    FloorRegion,
    StoreConfig,
    ZoneName,
)

STORE_CONFIG = StoreConfig(
    store_id="ST1008",
    store_name="Brigade_Bangalore",
    clips_dir="Store_1/Store 1",
    clip_start_iso="2026-04-10T20:10:00+05:30",  # burnt-in CCTV overlay (~20:10 IST, 10-Apr-2026)
    cameras=[
        CameraConfig(
            camera_id="CAM1",
            file="CAM 1 - zone.mp4",
            role=CameraRole.PRODUCT,
            primary_zone=ZoneName.SKINCARE_AISLE,
            fps=29.97,
        ),
        CameraConfig(
            camera_id="CAM2",
            file="CAM 2 - zone.mp4",
            role=CameraRole.PRODUCT,
            primary_zone=ZoneName.MAKEUP_AISLE,
            fps=29.97,
        ),
        CameraConfig(
            camera_id="CAM3",
            file="CAM 3 - entry.mp4",
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
            camera_id="CAM5",
            file="CAM 5 - billing.mp4",
            role=CameraRole.CHECKOUT,
            primary_zone=ZoneName.CHECKOUT,
            fps=24.98,
            # Walkable shopping floor at the checkout. Excludes the BACK DOORWAY (top-centre) and
            # the backlit ACCESSORIES display / mirror band (right) — detections there are
            # reflections / partial people at the back threshold, not shoppers on the floor
            # (Slice 2.4b diagnostic: phantom tracks had foot-points at y~220, off the floor).
            # Calibrated via scripts/calibrate_floor.py. See GROUND_TRUTH §1 / ADR-0010.
            floor_region=FloorRegion(
                vertices=[
                    (120, 1080),
                    (1310, 1080),
                    (1330, 700),
                    (1180, 460),
                    (740, 400),
                    (430, 470),
                    (170, 760),
                ],
                calibrated=True,
            ),
        ),
    ],
)
