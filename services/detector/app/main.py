"""detector service.

Runs YOLO + ByteTrack over **every configured store** (the pluggable `shelfsense_common.stores`
registry, ADR-0028) — each store's clips live under its own `clips_dir` beneath the CCTV mount, and
each store gets its own Re-ID identity space, staff decisions, zone labels and clip start. For each
tracked person on a customer camera it:
  - builds a lightweight appearance signature and resolves a GLOBAL `visitor_id` via the gallery
    (the same shopper across cameras / returning collapses to ONE id — ADR-0007/0008),
  - emits ZONE_ENTER / ZONE_DWELL / ZONE_EXIT for the camera's primary zone (ZoneTracker),
  - emits ENTRY / EXIT on the entrance line (CAM3) and REENTRY when a known visitor returns,
  - flags `is_staff` via the optional VLM, falling back to a per-store uniform-COLOUR match
    (black for Store_1, pink for Store_2; ADR-0009/0032/0027),
  - on cameras with a calibrated floor mask (CAM5), drops detections whose foot-point is off the
    walkable floor — mirror reflections / backlit displays at the back (ADR-0010).

All events are the prescribed flat `BehaviorEvent` written to a JSONL sink (no broker, ADR-0005).
Clips are finite recordings, so the service processes them once and then idles healthy.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from shelfsense_common.config import Settings, get_settings
from shelfsense_common.contracts import (
    BehaviorEvent,
    BehaviorEventType,
    CameraConfig,
    CameraRole,
    EventMetadata,
    StoreConfig,
)
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.sinks import EventSink, FanOutSink, HttpEventSink, JsonlEventSink
from shelfsense_common.stores import all_stores
from shelfsense_common.worker import GracefulRunner

from app.association import build_associator
from app.billing import BillingTracker
from app.crossing import CrossingDetector
from app.embedding import build_embedder
from app.frames import VideoFrameSource
from app.gating import passes_size_gate
from app.reid import SIGNATURE_LEN, ReIDGallery, appearance_signature
from app.staff import StaffClassifier, measure_uniform_color
from app.staff_decider import StaffDecider
from app.track import PersonTracker
from app.visits import VisitorRegistry
from app.vlm import JsonFileCache, build_vlm_client
from app.zone_resolver import resolve_zones
from app.zone_tracker import ZoneEvent, ZoneTracker

SERVICE = "detector"


def process_camera(
    store: StoreConfig,
    camera: CameraConfig,
    clip_path: Path,
    clip_start: datetime,
    tracker: PersonTracker,
    registry: VisitorRegistry,
    staff: StaffDecider,
    sink: EventSink,
    settings: Settings,
    log,
    emitted_visitors: set[str],
    exited_visitors: set[str],
    embedder,
    zone_override: str | None = None,
) -> dict[str, int]:
    """Track one camera; emit zone + entrance + reentry events with global (Re-ID'd) visitor ids."""
    # The zone this camera's events carry: the VLM's label when it confidently read the shelves
    # (zone_override), else the static hand-mapped primary_zone (ADR-0027). One value for the clip.
    zone_value = zone_override or camera.primary_zone.value
    # Count unique visitors from EVERY camera (ADR-0029, refining ADR-0011): each camera runs a zone
    # tracker, and Re-ID de-dups a person seen on several cameras into one visitor. Mall pass-by on
    # the entrance camera is discarded by the calibrated entrance line — only store-INTERIOR
    # detections feed the zone tracker (the inside-line filter in the frame loop) — and tiny
    # far/reflection blobs are dropped by the box-size gate. The entrance thus contributes interior
    # visitors too, not just crossings, without re-admitting the corridor traffic (ADR-0011).
    min_zone_dwell_ms = (
        store.min_zone_dwell_ms if store.min_zone_dwell_ms is not None
        else settings.min_zone_dwell_ms
    )
    zone_tracker = ZoneTracker(
        zone=zone_value,
        min_zone_dwell_ms=min_zone_dwell_ms,
        dwell_interval_ms=settings.zone_dwell_interval_ms,
        exit_grace_ms=settings.zone_exit_grace_ms,
    )
    crossing = (
        CrossingDetector(camera.entrance_line, confirm_frames=settings.crossing_confirm_frames)
        if camera.entrance_line is not None
        else None
    )
    # Billing-queue detection runs only on the CHECKOUT camera (CAM5); off its ZONE_ENTER/EXIT.
    billing = BillingTracker() if camera.role is CameraRole.CHECKOUT else None
    counts = {
        "frames": 0,
        "entries": 0,
        "exits": 0,
        "zone": 0,
        "reentry": 0,
        "off_floor": 0,
        "too_small": 0,
        "billing": 0,
    }
    # Running appearance signature per track (sum of per-frame embeddings) until resolved. Backend:
    # the learned CNN embedding (view-invariant) when an embedder is configured, else the colour
    # histogram. Both return unit vectors with the same (image, x, y, w, h) signature.
    sig_dim = embedder.dim if embedder is not None else SIGNATURE_LEN
    sig_sums: dict[int, np.ndarray] = {}

    def accumulate_signature(track_id: int, image: np.ndarray, bbox) -> None:
        if registry.is_resolved(camera.camera_id, track_id):
            return  # already has a global id — no need to keep sampling appearance
        x, y, w, h = int(bbox.x), int(bbox.y), int(bbox.w), int(bbox.h)
        sig = (
            embedder.extract(image, x, y, w, h)
            if embedder is not None
            else appearance_signature(image, x, y, w, h)
        )
        prev = sig_sums.get(track_id)
        sig_sums[track_id] = sig if prev is None else prev + sig
        # 2. Heuristic fallback: measure match to the store's staff uniform colour
        color_score = measure_uniform_color(
            image, x, y, w, h,
            store.staff_heuristic_color,
            settings.staff_uniform_v_max,
        )
        staff.observe(camera.camera_id, track_id, color_score)

    def current_signature(track_id: int) -> np.ndarray:
        vec = sig_sums.get(track_id)
        if vec is None:
            return np.zeros(sig_dim, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec

    def write_event(
        visitor_id: str,
        event_type: BehaviorEventType,
        ts_ms: int,
        confidence: float,
        zone_id: str | None,
        dwell_ms: int,
        is_staff: bool,
        queue_depth: int | None = None,
    ) -> None:
        event = BehaviorEvent(
            store_id=store.store_id,
            camera_id=camera.camera_id,
            visitor_id=visitor_id,
            event_type=event_type,
            timestamp=clip_start + timedelta(milliseconds=ts_ms),
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            is_staff=is_staff,
            confidence=confidence,
            metadata=EventMetadata(
                session_seq=registry.next_seq(visitor_id), queue_depth=queue_depth
            ),
        )
        sink.write(event)
        emitted_visitors.add(f"{store.store_id}:{visitor_id}")  # store-scoped so ids can't collide
        key = {
            BehaviorEventType.ENTRY: "entries",
            BehaviorEventType.EXIT: "exits",
            BehaviorEventType.REENTRY: "reentry",
            BehaviorEventType.BILLING_QUEUE_JOIN: "billing",
        }.get(event_type, "zone")
        counts[key] += 1

    def emit(
        track_id: int,
        event_type: BehaviorEventType,
        ts_ms: int,
        confidence: float,
        *,
        zone_id: str | None,
        dwell_ms: int,
        queue_depth: int | None = None,
    ) -> None:
        res = registry.resolve(camera.camera_id, track_id, current_signature(track_id), ts_ms)
        is_staff = staff.is_staff(camera.camera_id, track_id, res.visitor_id, dwell_ms)
        # REENTRY only for a visitor who actually LEFT the store (a prior EXIT across the entrance
        # line) and is now seen again — per EVENT_SCHEMA: "same visitor_id seen after a prior EXIT".
        # A gap-based Re-ID re-match on its own is just track fragmentation (a briefly occluded
        # shopper re-identified), so on clips where nobody exits this correctly stays 0 instead of
        # firing once per occlusion gap.
        if res.is_reentry and res.visitor_id in exited_visitors:
            write_event(
                res.visitor_id, BehaviorEventType.REENTRY, ts_ms, confidence, None, 0, is_staff
            )
            exited_visitors.discard(res.visitor_id)  # one re-entry per prior exit
        write_event(
            res.visitor_id, event_type, ts_ms, confidence, zone_id, dwell_ms, is_staff, queue_depth
        )
        if event_type is BehaviorEventType.EXIT:
            exited_visitors.add(res.visitor_id)  # arm a future REENTRY for this visitor

    def emit_zone(ze: ZoneEvent) -> None:
        emit(
            ze.track_id,
            ze.event_type,
            ze.ts_ms,
            ze.confidence,
            zone_id=ze.zone,
            dwell_ms=ze.dwell_ms,
        )
        if billing is None:  # only the checkout camera has billing
            return
        if ze.event_type is BehaviorEventType.ZONE_ENTER:
            # Internal billing gate only — visitor isn't resolved here, so use the heuristic
            # (visitor_id=None). The emitted BILLING event below re-decides is_staff with the VLM.
            is_staff = staff.is_staff(camera.camera_id, ze.track_id, None, ze.dwell_ms)
            for be in billing.join(ze.track_id, ze.ts_ms, ze.confidence, is_staff=is_staff):
                emit(
                    be.track_id,
                    be.event_type,
                    be.ts_ms,
                    be.confidence,
                    zone_id=zone_value,
                    dwell_ms=0,
                    queue_depth=be.queue_depth,
                )
        elif ze.event_type is BehaviorEventType.ZONE_EXIT:
            billing.leave(ze.track_id)

    tracker.reset()  # fresh per-camera track ids
    last_ts = 0
    with VideoFrameSource(clip_path, sample_fps=settings.tracker_sample_fps) as src:
        log.info(
            "camera_open",
            camera=camera.camera_id,
            zone=zone_value,
            fps=src.source_fps,
        )
        frame_h, frame_w = (src.height, src.width)
        # Tracklet stitching (ADR-0037): collapse fragmented ByteTrack ids into ONE stable LOCAL id
        # by motion BEFORE the appearance gallery, so a shopper split front/back stays one visitor.
        # Built per camera (positions are camera-local + frame-scaled); IdentityAssociator = legacy.
        associator = build_associator(settings, frame_w, frame_h)
        log.info("associator_open", camera=camera.camera_id, kind=type(associator).__name__)
        for frame in src.frames():
            last_ts = frame.ts_ms
            for track in tracker.update(frame.image):
                fx, fy = track.foot_point
                # Quality gate (ADR-0029): drop tiny far/reflection blobs entirely (mall pedestrians
                # seen small through the storefront glass). Applies before counting AND crossing.
                if not passes_size_gate(
                    track.bbox.w, track.bbox.h, frame_w, frame_h, settings.min_detection_box_frac
                ):
                    counts["too_small"] += 1
                    continue
                # Walkable-floor mask (where calibrated): reflections / wall displays aren't on the
                # floor. Drops entirely (not a real shopper).
                if camera.floor_region is not None and not camera.floor_region.contains(fx, fy):
                    counts["off_floor"] += 1
                    continue
                # Stitch this raw track to a stable local id (after the gates, so reflections /
                # pass-by blobs never seed a local). Everything downstream — signature, staff,
                # zone dwell, crossings — keys on local_id, so a fragmented person is ONE track.
                local_id = associator.assign(track.track_id, fx, fy, frame.ts_ms)
                accumulate_signature(local_id, frame.image, track.bbox)
                # Capture a representative crop for the VLM staff call (no-op without a VLM). Done
                # outside accumulate_signature so a quickly-resolved track still gets a crop.
                staff.observe_crop(camera.camera_id, local_id, frame.image, track.bbox)
                # Pass-by filter (ADR-0029): on a camera with an entrance line, only store-INTERIOR
                # detections count as visitors — mall corridor traffic stays out of the zone count.
                # The crossing detector below still sees both sides, so it can detect entries.
                inside_ok = camera.entrance_line is None or camera.entrance_line.is_inside(fx, fy)
                if inside_ok:
                    for ze in zone_tracker.observe(local_id, frame.ts_ms, track.confidence):
                        emit_zone(ze)
                if crossing is not None:
                    for cross in crossing.update(
                        local_id, fx, fy, frame.ts_ms, track.confidence
                    ):
                        emit(
                            cross.track_id,
                            cross.event_type,
                            cross.ts_ms,
                            cross.confidence,
                            zone_id=None,
                            dwell_ms=0,
                        )
            for ze in zone_tracker.sweep(frame.ts_ms):  # close tracks that left the zone
                emit_zone(ze)
            counts["frames"] += 1
            if settings.detector_max_frames and counts["frames"] >= settings.detector_max_frames:
                break
    for ze in zone_tracker.flush(last_ts):  # close anyone still present at clip end
        emit_zone(ze)

    log.info("camera_processed", store=store.store_id, camera=camera.camera_id, **counts)
    return counts


def _clip_start_for(store: StoreConfig, settings: Settings) -> datetime:
    """Store-local clip start: the store's own `clip_start_iso`, else the global default."""
    return datetime.fromisoformat(store.clip_start_iso or settings.clip_start_iso)


def _enabled_filter(settings: Settings) -> set[str]:
    """Optional camera allow-list from `ENABLED_CAMERAS` (normalised), applied across all stores."""
    return {
        c.strip().upper().replace(" ", "") for c in settings.enabled_cameras.split(",") if c.strip()
    }


def process_store(
    store: StoreConfig,
    cctv_dir: Path,
    tracker: PersonTracker,
    sink: EventSink,
    vlm,
    vlm_cache,
    embedder,
    settings: Settings,
    log,
    emitted_visitors: set[str],
    http_sink: HttpEventSink | None,
) -> dict[str, int]:
    """Process one store end to end: its own Re-ID gallery, staff decider, zone labels, clip start.

    Each store is isolated — a visitor in one store is never the same identity as in another — so
    the gallery/registry/staff state is rebuilt per store. The shared YOLO tracker is reset per cam.
    """
    store_dir = cctv_dir / store.clips_dir
    cameras = store.customer_cameras
    allow = _enabled_filter(settings)
    if allow:
        cameras = [c for c in cameras if c.camera_id in allow]
    if not cameras:
        return {}

    # Re-ID distance. The CNN embedding lives in a different metric space from the colour histogram,
    # so it uses the global `reid_cnn_max_distance`; the histogram backend keeps the per-store
    # density tuning (store override → global default).
    if embedder is not None:
        reid_max_distance = settings.reid_cnn_max_distance
    else:
        reid_max_distance = (
            store.reid_max_distance if store.reid_max_distance is not None
            else settings.reid_max_distance
        )
    tracker.imgsz = (
        store.detector_imgsz
        if store.detector_imgsz is not None
        else settings.detector_imgsz
    )
    registry = VisitorRegistry(
        ReIDGallery(
            max_distance=reid_max_distance,
            reentry_min_gap_ms=settings.reid_reentry_min_gap_ms,
        )
    )
    heuristic_staff = StaffClassifier(
        threshold=settings.staff_uniform_threshold,
        presence_fallback_ms=(
            settings.staff_min_presence_ms if settings.staff_presence_fallback else None
        ),
    )
    staff = StaffDecider(
        heuristic_staff,
        vlm,
        vlm_cache,
        store.store_id,
        staff_hint=store.staff_uniform_hint,
        min_confidence=settings.vlm_staff_min_confidence,
        classify_staff=settings.vlm_classify_staff,
        override_margin=settings.staff_override_margin,
        log=log,
        crop_dump_dir=settings.staff_crop_dump_dir,
    )
    # Label product-camera zones from the shelves (VLM), falling back to the static primary_zone.
    zone_overrides = resolve_zones(
        cameras, store_dir, vlm, vlm_cache, settings, store.store_id, log
    )
    clip_start = _clip_start_for(store, settings)
    # Visitors who crossed the entrance line outbound (EXIT); seeing them again arms a REENTRY.
    # Per-store + shared across this store's cameras (the gallery/identity space is per-store).
    exited_visitors: set[str] = set()
    log.info(
        "store_open",
        store=store.store_id,
        clips_dir=store.clips_dir,
        cameras=[c.camera_id for c in cameras],
        clip_start=clip_start.isoformat(),
    )

    totals: dict[str, int] = {}
    for camera in cameras:
        clip_path = store_dir / camera.file
        if not clip_path.exists():
            log.warning(
                "clip_missing", store=store.store_id, camera=camera.camera_id, path=str(clip_path)
            )
            continue
        counts = process_camera(
            store,
            camera,
            clip_path,
            clip_start,
            tracker,
            registry,
            staff,
            sink,
            settings,
            log,
            emitted_visitors,
            exited_visitors,
            embedder,
            zone_override=zone_overrides.get(camera.camera_id),
        )
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
        # Incremental flush (ADR-0018): push THIS camera's events to the API as soon as it's done,
        # so the endpoints populate progressively across the run instead of only at the final exit.
        sink.flush()
        if http_sink is not None:
            log.info(
                "camera_posted",
                store=store.store_id,
                camera=camera.camera_id,
                posted_to_api=http_sink.posted,
            )
    staff.dump_crops()  # no-op unless STAFF_CROP_DUMP_DIR is set (proof/adjudication aid)
    return totals


def run_once(settings: Settings, log) -> dict[str, int]:
    """Process every configured store's cameras once and write events. Returns aggregate counts.

    Stores come from the pluggable registry (`all_stores()`), so onboarding a store needs no change
    here. Shared across stores: the YOLO tracker, the event sinks, and the (optional) VLM + its
    cache. Isolated per store: Re-ID / identity / staff decisions / zone labels / clip start.
    """
    cctv_dir = Path(settings.cctv_dir)
    stores = all_stores()
    allow_stores = {s.strip().upper() for s in settings.enabled_stores.split(",") if s.strip()}
    if allow_stores:  # optional filter (e.g. process only one store)
        stores = [s for s in stores if s.store_id.upper() in allow_stores]
        log.info(
            "detector_boot",
            model=settings.yolo_model,
            confidence=settings.detection_confidence,
            iou=settings.detection_iou,
            tracker=settings.tracker_cfg,
            sample_fps=settings.tracker_sample_fps,
            imgsz=settings.detector_imgsz,
            reid_max_distance=settings.reid_max_distance,
            stores=[s.store_id for s in stores],
            events_path=settings.events_jsonl_path,
        )

    tracker = PersonTracker(
        settings.yolo_model,
        settings.detection_confidence,
        settings.person_class_id,
        tracker_cfg=settings.tracker_cfg,
        imgsz=settings.detector_imgsz,
        iou=settings.detection_iou,
    )

    # Optional VLM (ADR-0027). build_vlm_client returns None when disabled / no key / SDK absent, so
    # the deciders quietly use the heuristic and `docker compose up` stays key/network-free. Built
    # once and shared across stores; the cache de-dups calls (keyed by store+visitor/store+camera).
    vlm = build_vlm_client(settings, log)
    vlm_cache = JsonFileCache(settings.vlm_cache_path) if vlm is not None else None

    # Optional learned Re-ID embedder (ADR-0036). None unless reid_backend="cnn"; falls back to the
    # colour histogram. Built once and shared (stateless feature extraction) across all stores.
    embedder = build_embedder(settings, log)

    totals: dict[str, int] = {}
    emitted_visitors: set[str] = set()  # distinct (store, visitor) ids that produced an event

    # Fan each event to the JSONL (inspectable + replayable) and, when enabled, straight to the API
    # via POST so `docker compose up` populates the endpoints with no manual replay (ADR-0015).
    # truncate: a single full detection pass re-exports the JSONL, never appends stale events.
    sinks: list[EventSink] = [JsonlEventSink(settings.events_jsonl_path, truncate=True)]
    http_sink: HttpEventSink | None = None
    if settings.detector_post_to_api:
        http_sink = HttpEventSink(
            settings.api_base_url,
            batch_size=settings.ingest_batch_size,
            wait_s=settings.ingest_wait_s,
            max_retries=settings.ingest_max_retries,
            log=log,
        )
        sinks.append(http_sink)

    with FanOutSink(sinks) as sink:
        for store in stores:
            store_totals = process_store(
                store,
                cctv_dir,
                tracker,
                sink,
                vlm,
                vlm_cache,
                embedder,
                settings,
                log,
                emitted_visitors,
                http_sink,
            )
            for key, value in store_totals.items():
                totals[key] = totals.get(key, 0) + value

    # Logged after the sinks close so the HTTP sink's final batch is already flushed/counted.
    # unique_visitors = distinct (store, visitor) ids that produced an event (Re-ID-deduped).
    posted = http_sink.posted if http_sink is not None else 0
    log.info(
        "detection_pass_complete",
        stores=len(stores),
        unique_visitors=len(emitted_visitors),
        posted_to_api=posted,
        **totals,
    )
    return {**totals, "unique_visitors": len(emitted_visitors)}

def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE, settings.log_level)
    log = get_logger(SERVICE)

    run_once(settings, log)

    # Recorded clips are finite: idle (healthy) once processed
    # instead of busy-reprocessing.
    GracefulRunner(SERVICE, interval_s=30.0).run(
        lambda i: log.info("idle", iteration=i),
    )


if __name__ == "__main__":
    main()

