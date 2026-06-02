"""Per-camera zone labelling via the VLM (ADR-0027).

Today each camera's zone is the hand-mapped `primary_zone` in zones.py. When a VLM is configured,
this resolver reads ONE representative frame per *product* camera and asks the model which retail
zone its shelves show — producing an override map `{camera_id: zone}` the detector applies instead
of the static label. This lets us auto-label a new store's shelves (e.g. Store_2) instead of
hand-mapping, and corrects a mislabelled aisle.

Scope + safety:
  * Only **product** cameras are classified — entrance/checkout/stockroom are role-known and their
    zones drive footfall/billing, so we never let the model relabel them.
  * The VLM may only pick from the existing zone vocabulary (`product_zone_candidates`), keeping
    `zone_id` consistent with the heatmap/analytics.
  * Confidence-gated, cached, and fully best-effort: a low-confidence verdict or any error leaves
    the static `primary_zone` untouched. Returns an empty map when the VLM is disabled.
"""

from __future__ import annotations

from pathlib import Path

from shelfsense_common.contracts import CameraConfig, CameraRole, ZoneName

from app.frames import VideoFrameSource
from app.vlm import JsonFileCache, VLMClient


def product_zone_candidates() -> list[str]:
    """The shelf-zone labels the VLM may choose from (excludes entrance/checkout/stockroom)."""
    excluded = {ZoneName.ENTRANCE, ZoneName.CHECKOUT, ZoneName.STOCKROOM}
    return [z.value for z in ZoneName if z not in excluded]


def resolve_zones(
    cameras: list[CameraConfig],
    cctv_dir: Path,
    vlm: VLMClient | None,
    cache: JsonFileCache | None,
    settings,
    store_id: str,
    log,
) -> dict[str, str]:
    """Return `{camera_id: zone}` overrides for product cameras the VLM labels confidently."""
    overrides: dict[str, str] = {}
    if vlm is None or not settings.vlm_classify_zone:
        return overrides
    candidates = product_zone_candidates()
    min_conf = settings.vlm_zone_min_confidence

    for camera in cameras:
        if camera.role is not CameraRole.PRODUCT:
            continue  # entrance/checkout/stockroom zones are role-known — don't relabel them
        cache_key = f"zone:{store_id}:{camera.camera_id}"
        cached = cache.get(cache_key) if cache is not None else None
        if cached is not None:
            zone, conf = str(cached.get("zone", "")), float(cached.get("confidence", 0.0))
            if zone in candidates and conf >= min_conf:
                overrides[camera.camera_id] = zone
            continue

        clip_path = cctv_dir / camera.file
        if not clip_path.exists():
            continue
        try:
            with VideoFrameSource(clip_path, sample_fps=settings.tracker_sample_fps) as src:
                frame = src.grab_frame(settings.vlm_zone_frame_fraction)
            verdict = vlm.classify_zone(frame.image, candidates)
        except Exception as err:  # noqa: BLE001 — keep the static zone, don't crash the pass
            log.warning("vlm_zone_failed", camera=camera.camera_id, error=str(err))
            continue

        if cache is not None:
            cache.set(
                cache_key,
                {"zone": verdict.zone, "confidence": verdict.confidence, "reason": verdict.reason},
            )
        log.info(
            "vlm_zone",
            camera=camera.camera_id,
            zone=verdict.zone,
            confidence=round(verdict.confidence, 3),
            static_zone=camera.primary_zone.value,
        )
        if verdict.zone in candidates and verdict.confidence >= min_conf:
            overrides[camera.camera_id] = verdict.zone
    return overrides
