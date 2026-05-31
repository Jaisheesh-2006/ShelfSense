"""detector service.

Slice 2.2 — footfall via the entrance camera. Runs YOLO + ByteTrack on the CAM3 clip, watches
each stable track cross the calibrated entrance line, and emits prescribed `ENTRY`/`EXIT`
behavioural events (EVENT_SCHEMA) to a JSONL sink. Clips are finite recordings, so the service
processes the clip once and then idles healthy.

Scope note: only the entrance camera is processed here — footfall is counted at the door, not on
the floor. Zone events on the product/checkout cameras (CAM1/CAM2/CAM5) and Re-ID/staff land in
Slices 2.3–2.4. The message broker was dropped (ADR-0005): events go to JSONL, ingested by the API
via POST in Slice 2.6.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from shelfsense_common.config import Settings, get_settings
from shelfsense_common.contracts import (
    STORE,
    BehaviorEvent,
    CameraConfig,
    EventMetadata,
)
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.sinks import JsonlEventSink
from shelfsense_common.worker import GracefulRunner

from app.crossing import CrossingDetector
from app.frames import VideoFrameSource
from app.track import PersonTracker

SERVICE = "detector"


def process_entrance(
    camera: CameraConfig,
    clip_path: Path,
    tracker: PersonTracker,
    sink: JsonlEventSink,
    settings: Settings,
    log,
) -> tuple[int, int, int]:
    """Track people across the entrance clip and emit ENTRY/EXIT events on line crossings.

    Returns (frames_processed, entries, exits).
    """
    if camera.entrance_line is None:
        raise ValueError(f"{camera.camera_id} has no calibrated entrance line")

    crossing = CrossingDetector(
        camera.entrance_line, confirm_frames=settings.crossing_confirm_frames
    )
    clip_start = settings.clip_start_dt
    frames_done = entries = exits = 0

    tracker.reset()  # fresh identities for this camera sequence
    with VideoFrameSource(clip_path, sample_fps=settings.tracker_sample_fps) as src:
        log.info("camera_open", camera=camera.camera_id, fps=src.source_fps, stride=src.stride)
        for frame in src.frames():
            for track in tracker.update(frame.image):
                fx, fy = track.foot_point
                for cross in crossing.update(track.track_id, fx, fy, frame.ts_ms, track.confidence):
                    event = BehaviorEvent(
                        store_id=STORE.store_id,
                        camera_id=camera.camera_id,
                        visitor_id=cross.visitor_id,
                        event_type=cross.event_type,
                        timestamp=clip_start + timedelta(milliseconds=cross.ts_ms),
                        zone_id=None,
                        dwell_ms=0,
                        is_staff=False,
                        confidence=cross.confidence,
                        metadata=EventMetadata(session_seq=cross.session_seq),
                    )
                    sink.write(event)
                    if cross.event_type.value == "ENTRY":
                        entries += 1
                    else:
                        exits += 1
                    log.info(
                        "behavior_event",
                        event_type=event.event_type.value,
                        visitor_id=event.visitor_id,
                        track_id=cross.track_id,
                        ts_ms=cross.ts_ms,
                        confidence=round(event.confidence, 3),
                    )
            frames_done += 1
            if settings.detector_max_frames and frames_done >= settings.detector_max_frames:
                break

    log.info(
        "camera_processed",
        camera=camera.camera_id,
        frames=frames_done,
        entries=entries,
        exits=exits,
    )
    return frames_done, entries, exits


def run_once(settings: Settings, log) -> tuple[int, int, int]:
    """Process the entrance clip once and write events. Returns (frames, entries, exits).

    Separated from `main()` so dev/demo tooling can run a single pass without the idle loop.
    """
    cctv_dir = Path(settings.cctv_dir)
    entrance = STORE.entrance_camera
    if entrance is None:
        raise RuntimeError("no entrance camera configured")

    log.info(
        "detector_boot",
        model=settings.yolo_model,
        confidence=settings.detection_confidence,
        tracker=settings.tracker_cfg,
        sample_fps=settings.tracker_sample_fps,
        entrance_camera=entrance.camera_id,
        events_path=settings.events_jsonl_path,
    )

    tracker = PersonTracker(
        settings.yolo_model,
        settings.detection_confidence,
        settings.person_class_id,
        tracker_cfg=settings.tracker_cfg,
    )

    clip_path = cctv_dir / entrance.file
    with JsonlEventSink(settings.events_jsonl_path) as sink:
        if not clip_path.exists():
            log.warning("clip_missing", camera=entrance.camera_id, path=str(clip_path))
            result = (0, 0, 0)
        else:
            result = process_entrance(entrance, clip_path, tracker, sink, settings, log)
        log.info("detection_pass_complete")
    return result


def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE, settings.log_level)
    log = get_logger(SERVICE)

    run_once(settings, log)

    # Recorded clip is finite: idle (healthy) once processed instead of busy-reprocessing.
    GracefulRunner(SERVICE, interval_s=30.0).run(lambda i: log.info("idle", iteration=i))


if __name__ == "__main__":
    main()
