"""detector service.

Reads each customer-area CCTV clip, runs YOLO person detection on sampled frames, and publishes
`detection.created` events to the stream. Clips are processed once (recorded footage), then the
service idles so the container stays healthy. The stockroom camera (CAM 4) is skipped — it is not
a customer area (see zones.py / GROUND_TRUTH §1).
"""
from __future__ import annotations

from pathlib import Path

from app.detect import PersonDetector
from app.frames import VideoFrameSource

from shelfsense_common.config import Settings, get_settings
from shelfsense_common.contracts import STORE, CameraConfig, DetectionCreated, EventType, make_event
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.stream import EventProducer
from shelfsense_common.worker import GracefulRunner

SERVICE = "detector"


def process_camera(
    camera: CameraConfig,
    clip_path: Path,
    detector: PersonDetector,
    producer: EventProducer,
    settings: Settings,
    log,
) -> tuple[int, int]:
    """Detect people across a clip and publish one detection.created event per sampled frame."""
    frames_done = 0
    detections_total = 0
    with VideoFrameSource(clip_path, sample_fps=settings.detector_sample_fps) as src:
        log.info("camera_open", camera=camera.camera_id, fps=src.source_fps, stride=src.stride)
        for frame in src.frames():
            detections = detector.detect(frame.image)
            event = make_event(
                EventType.DETECTION_CREATED,
                DetectionCreated(
                    camera_id=camera.camera_id,
                    frame_id=frame.index,
                    ts_ms=frame.ts_ms,
                    detections=detections,
                ),
                source=SERVICE,
            )
            producer.publish(settings.topic_detections, event, key=camera.camera_id)
            frames_done += 1
            detections_total += len(detections)
            if settings.detector_max_frames and frames_done >= settings.detector_max_frames:
                break
    log.info(
        "camera_processed",
        camera=camera.camera_id,
        frames=frames_done,
        detections=detections_total,
    )
    return frames_done, detections_total


def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE, settings.log_level)
    log = get_logger(SERVICE)

    cctv_dir = Path(settings.cctv_dir)
    cameras = [c for c in STORE.cameras if c.is_customer_area]
    log.info(
        "detector_boot",
        model=settings.yolo_model,
        confidence=settings.detection_confidence,
        cctv_dir=str(cctv_dir),
        cameras=[c.camera_id for c in cameras],
    )

    detector = PersonDetector(
        settings.yolo_model, settings.detection_confidence, settings.person_class_id
    )

    with EventProducer(settings.stream_bootstrap_servers, client_id=SERVICE) as producer:
        for camera in cameras:
            clip_path = cctv_dir / camera.file
            if not clip_path.exists():
                log.warning("clip_missing", camera=camera.camera_id, path=str(clip_path))
                continue
            process_camera(camera, clip_path, detector, producer, settings, log)
        log.info("detection_pass_complete")

    # Recorded clips are finite: idle (healthy) once processed instead of busy-reprocessing.
    GracefulRunner(SERVICE, interval_s=30.0).run(lambda i: log.info("idle", iteration=i))


if __name__ == "__main__":
    main()
