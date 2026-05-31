"""detector service — Phase 1 scaffold.

Responsibility (Phase 2): read frames from each CCTV clip, run YOLO person detection, and emit
`detection.created` events to the stream. For now it boots, logs config, and heartbeats so the
container stays healthy in `docker compose up`. Real detection logic lands in Phase 2.

See docs/wiki/ARCHITECTURE.md and docs/wiki/TASKS.md (Phase 2).
"""
from __future__ import annotations

from shelfsense_common.config import get_settings
from shelfsense_common.contracts import STORE
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.worker import GracefulRunner

SERVICE = "detector"


def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE, settings.log_level)
    log = get_logger(SERVICE)
    log.info(
        "detector_boot",
        model=settings.yolo_model,
        confidence=settings.detection_confidence,
        cameras=[c.camera_id for c in STORE.cameras],
        note="Phase 1 scaffold — YOLO detection arrives in Phase 2",
    )

    def tick(i: int) -> None:
        log.info("heartbeat", iteration=i)

    GracefulRunner(SERVICE, interval_s=15.0).run(tick)


if __name__ == "__main__":
    main()
