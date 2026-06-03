# Store registry — adding a store is a drop-in

This package is the **single source of truth for store layouts** (cameras, zones, entrance lines,
clip locations). It is **auto-discovered**: every module here that exposes a module-level
`STORE_CONFIG` is registered at import (keyed by `store_id`, see `__init__.py`). The detector,
analytics, and the API all read this registry, so a new store flows through the whole system with no
code changes. (ADR-0028.)

## Add a new store in 3 steps

1. **Drop a config file** `stores/<store_id>.py` (copy `st1009.py`):
   ```python
   from shelfsense_common.contracts.zones import (
       CameraConfig, CameraRole, EntranceLine, FloorRegion, StoreConfig, ZoneName,
   )

   STORE_CONFIG = StoreConfig(
       store_id="ST1010",
       store_name="My_New_Store",
       clips_dir="My_Store/clips",          # relative to the CCTV mount (CCTV_DIR)
       clip_start_iso="2026-04-10T10:00:00+05:30",  # optional; omit to use the global CLIP_START_ISO
       cameras=[
           CameraConfig(camera_id="ENTRY", file="entry.mp4", role=CameraRole.ENTRANCE,
                        primary_zone=ZoneName.ENTRANCE, fps=25.0,
                        entrance_line=EntranceLine(x1=..., y1=..., x2=..., y2=..., inside_sign=1)),
           CameraConfig(camera_id="ZONE", file="zone.mp4", role=CameraRole.PRODUCT,
                        primary_zone=ZoneName.MAKEUP_AISLE, fps=25.0),
           CameraConfig(camera_id="BILLING", file="billing.mp4", role=CameraRole.CHECKOUT,
                        primary_zone=ZoneName.CHECKOUT, fps=25.0),
       ],
   )
   ```

2. **Put the clips** under `CCTV_DIR/<clips_dir>/` (the one CCTV mount holds every store).

3. **(Optional) list it for the dashboard** — add `"<store_id>:<Display Name>"` to the `STORES`
   env var so the store switcher shows it.

That's it. The detector will process the new store on its next run; the API serves its metrics
automatically (no API change — it's per-store already).

## Field reference

| Field | Meaning |
|-------|---------|
| `store_id` | Stable id used on every event and in the API path (`/stores/{id}/...`). |
| `clips_dir` | Folder (relative to `CCTV_DIR`) holding this store's clips. |
| `clip_start_iso` | Store-local wall-clock start of the clips → absolute UTC timestamps. `None` ⇒ global `CLIP_START_ISO`. Use it to pin clips spanning different days onto one synthetic day. |
| `CameraConfig.role` | `ENTRANCE` (footfall via `entrance_line`, no zone visitors), `PRODUCT` (zone visitors), `CHECKOUT` (billing queue), `STOCKROOM` (`is_customer_area=False`, excluded). |
| `entrance_line` | Virtual counting line in **pixel coords of that camera's frame**; `inside_sign` says which side is the store interior. `calibrated=False` flags a placeholder. |
| `floor_region` | Optional walkable-floor polygon; foot-points outside it are dropped (suppresses mirror/display phantoms). Omit to fail open. |

## Calibration notes
- Entrance lines and floor regions are **per-camera pixel coordinates** — they must be set against
  that store's actual frames (different resolutions are fine: ST1008 is 1920×1080, ST1009 is 960×1080).
- **Zone labels** can be left as sensible defaults — when `VLM_ENABLED=true`, the VLM relabels each
  product camera's zone from its shelves (ADR-0027). Entrance/checkout/stockroom are role-known.
- Stores without POS (e.g. ST1009) compute everything except **conversion**, which is reported as
  not-available rather than a misleading 0.
