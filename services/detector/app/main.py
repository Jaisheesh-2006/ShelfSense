"""detector service.

Slice 2.4 — Re-ID + edge cases. Runs YOLO + ByteTrack on every customer camera (CAM1/2/3/5; CAM4 is
the staff back room and is skipped). For each tracked person it:
  - builds a lightweight appearance signature and resolves a GLOBAL `visitor_id` via the gallery
    (the same shopper across cameras / returning collapses to ONE id — ADR-0007/0008),
  - emits ZONE_ENTER / ZONE_DWELL / ZONE_EXIT for the camera's primary zone (ZoneTracker),
  - emits ENTRY / EXIT on the entrance line (CAM3) and REENTRY when a known visitor returns,
  - flags `is_staff` by DARK-UNIFORM appearance (Brigade staff wear complete black; ADR-0009),
  - on cameras with a calibrated floor mask (CAM5), drops detections whose foot-point is off the
    walkable floor — mirror reflections / backlit displays at the back (ADR-0010).

All events are the prescribed flat `BehaviorEvent` written to a JSONL sink (no broker, ADR-0005).
Clips are finite recordings, so the service processes them once and then idles healthy.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
from shelfsense_common.config import Settings, get_settings
from shelfsense_common.contracts import (
    STORE,
    BehaviorEvent,
    BehaviorEventType,
    CameraConfig,
    CameraRole,
    EventMetadata,
)
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.sinks import EventSink, FanOutSink, HttpEventSink, JsonlEventSink
from shelfsense_common.worker import GracefulRunner

from app.billing import BillingTracker
from app.crossing import CrossingDetector
from app.frames import VideoFrameSource
from app.reid import SIGNATURE_LEN, ReIDGallery, appearance_signature
from app.staff import StaffClassifier, uniform_darkness
from app.track import PersonTracker
from app.visits import VisitorRegistry
from app.zone_tracker import ZoneEvent, ZoneTracker

SERVICE = "detector"


def process_camera(
    camera: CameraConfig,
    clip_path: Path,
    tracker: PersonTracker,
    registry: VisitorRegistry,
    staff: StaffClassifier,
    sink: EventSink,
    settings: Settings,
    log,
    emitted_visitors: set[str],
) -> dict[str, int]:
    """Track one camera; emit zone + entrance + reentry events with global (Re-ID'd) visitor ids."""
    clip_start = settings.clip_start_dt
    # The ENTRANCE camera contributes FOOTFALL (ENTRY/EXIT crossings) only — not zone-visitor
    # counts: it looks onto the mall corridor, so its zone detections are dominated by pass-by
    # pedestrians, not shoppers (ADR-0011, refining ADR-0007). Visitors come from the floor cams.
    zone_enabled = camera.role is not CameraRole.ENTRANCE
    zone_tracker = (
        ZoneTracker(
            zone=camera.primary_zone.value,
            min_zone_dwell_ms=settings.min_zone_dwell_ms,
            dwell_interval_ms=settings.zone_dwell_interval_ms,
            exit_grace_ms=settings.zone_exit_grace_ms,
        )
        if zone_enabled
        else None
    )
    crossing = (
        CrossingDetector(camera.entrance_line, confirm_frames=settings.crossing_confirm_frames)
        if camera.entrance_line is not None
        else None
    )
    # Billing-queue detection runs only on the CHECKOUT camera (CAM5); off its ZONE_ENTER/EXIT.
    billing = BillingTracker() if camera.role is CameraRole.CHECKOUT else None
    counts = {
        "frames": 0, "entries": 0, "exits": 0, "zone": 0,
        "reentry": 0, "off_floor": 0, "billing": 0,
    }
    # Running appearance signature per track (sum of per-frame histograms) until resolved.
    sig_sums: dict[int, np.ndarray] = {}

    def accumulate_signature(track_id: int, image: np.ndarray, bbox) -> None:
        if registry.is_resolved(camera.camera_id, track_id):
            return  # already has a global id — no need to keep sampling appearance
        x, y, w, h = int(bbox.x), int(bbox.y), int(bbox.w), int(bbox.h)
        sig = appearance_signature(image, x, y, w, h)
        prev = sig_sums.get(track_id)
        sig_sums[track_id] = sig if prev is None else prev + sig
        # Same crop, different measure: how black is this person's outfit? (staff uniform signal)
        darkness = uniform_darkness(image, x, y, w, h, settings.staff_dark_v_max)
        staff.observe(camera.camera_id, track_id, darkness)

    def current_signature(track_id: int) -> np.ndarray:
        vec = sig_sums.get(track_id)
        if vec is None:
            return np.zeros(SIGNATURE_LEN, dtype=np.float32)
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
            store_id=STORE.store_id,
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
        emitted_visitors.add(visitor_id)
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
        is_staff = staff.is_staff(camera.camera_id, track_id, dwell_ms)
        if res.is_reentry:  # known visitor returning after an absence — flag before the main event
            write_event(
                res.visitor_id, BehaviorEventType.REENTRY, ts_ms, confidence, None, 0, is_staff
            )
        write_event(
            res.visitor_id, event_type, ts_ms, confidence, zone_id, dwell_ms, is_staff, queue_depth
        )

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
            is_staff = staff.is_staff(camera.camera_id, ze.track_id, ze.dwell_ms)
            for be in billing.join(ze.track_id, ze.ts_ms, ze.confidence, is_staff=is_staff):
                emit(
                    be.track_id,
                    be.event_type,
                    be.ts_ms,
                    be.confidence,
                    zone_id=camera.primary_zone.value,
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
            zone=camera.primary_zone.value,
            fps=src.source_fps,
        )
        for frame in src.frames():
            last_ts = frame.ts_ms
            for track in tracker.update(frame.image):
                if camera.floor_region is not None:
                    fx, fy = track.foot_point
                    if not camera.floor_region.contains(fx, fy):
                        counts["off_floor"] += 1  # reflection / wall display — not on the floor
                        continue
                accumulate_signature(track.track_id, frame.image, track.bbox)
                if zone_tracker is not None:
                    for ze in zone_tracker.observe(track.track_id, frame.ts_ms, track.confidence):
                        emit_zone(ze)
                if crossing is not None:
                    fx, fy = track.foot_point
                    for cross in crossing.update(
                        track.track_id, fx, fy, frame.ts_ms, track.confidence
                    ):
                        emit(
                            cross.track_id,
                            cross.event_type,
                            cross.ts_ms,
                            cross.confidence,
                            zone_id=None,
                            dwell_ms=0,
                        )
            if zone_tracker is not None:
                for ze in zone_tracker.sweep(frame.ts_ms):  # close tracks that left the zone
                    emit_zone(ze)
            counts["frames"] += 1
            if settings.detector_max_frames and counts["frames"] >= settings.detector_max_frames:
                break
    if zone_tracker is not None:
        for ze in zone_tracker.flush(last_ts):  # close anyone still present at clip end
            emit_zone(ze)

    log.info("camera_processed", camera=camera.camera_id, **counts)
    return counts


def run_once(settings: Settings, log) -> dict[str, int]:
    """Process every customer camera once and write events. Returns aggregate counts."""
    cctv_dir = Path(settings.cctv_dir)
    cameras = [c for c in STORE.cameras if c.is_customer_area]
    allow = {
        c.strip().upper().replace(" ", "")
        for c in settings.enabled_cameras.split(",")
        if c.strip()
    }
    if allow:  # optional filter (e.g. only the cameras a reviewer can ground-truth)
        cameras = [c for c in cameras if c.camera_id in allow]
    log.info(
        "detector_boot",
        model=settings.yolo_model,
        confidence=settings.detection_confidence,
        tracker=settings.tracker_cfg,
        sample_fps=settings.tracker_sample_fps,
        reid_max_distance=settings.reid_max_distance,
        cameras=[c.camera_id for c in cameras],
        events_path=settings.events_jsonl_path,
    )

    tracker = PersonTracker(
        settings.yolo_model,
        settings.detection_confidence,
        settings.person_class_id,
        tracker_cfg=settings.tracker_cfg,
    )
    gallery = ReIDGallery(
        max_distance=settings.reid_max_distance,
        reentry_min_gap_ms=settings.reid_reentry_min_gap_ms,
    )
    registry = VisitorRegistry(gallery)
    staff = StaffClassifier(
        threshold=settings.staff_darkness_threshold,
        presence_fallback_ms=(
            settings.staff_min_presence_ms if settings.staff_presence_fallback else None
        ),
    )
    totals = {
        "frames": 0, "entries": 0, "exits": 0, "zone": 0,
        "reentry": 0, "off_floor": 0, "billing": 0,
    }
    emitted_visitors: set[str] = set()  # distinct GLOBAL visitors who produced an event

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
        for camera in cameras:
            clip_path = cctv_dir / camera.file
            if not clip_path.exists():
                log.warning("clip_missing", camera=camera.camera_id, path=str(clip_path))
                continue
            counts = process_camera(
                camera, clip_path, tracker, registry, staff, sink, settings, log, emitted_visitors
            )
            for key, value in counts.items():
                totals[key] += value

    # Logged after the sinks close so the HTTP sink's final batch is already flushed/counted.
    # unique_visitors = distinct GLOBAL ids that produced an event (Re-ID-deduped).
    posted = http_sink.posted if http_sink is not None else 0
    log.info(
        "detection_pass_complete",
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

    # Recorded clips are finite: idle (healthy) once processed instead of busy-reprocessing.
    GracefulRunner(SERVICE, interval_s=30.0).run(lambda i: log.info("idle", iteration=i))


if __name__ == "__main__":
    main()
