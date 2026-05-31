"""tracker service — Phase 1 scaffold.

Responsibility (Phase 2): consume `detection.created`, associate detections into tracks with
ByteTrack, map each track to a store zone (entrance line-crossing on CAM 3), and emit
`track.updated`. For now it boots, logs, and heartbeats. Real tracking lands in Phase 2.
"""
from __future__ import annotations

from shelfsense_common.config import get_settings
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.worker import GracefulRunner

SERVICE = "tracker"


def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE, settings.log_level)
    log = get_logger(SERVICE)
    log.info(
        "tracker_boot",
        consumes=settings.topic_detections,
        produces=settings.topic_tracks,
        note="Phase 1 scaffold — ByteTrack association arrives in Phase 2",
    )

    def tick(i: int) -> None:
        log.info("heartbeat", iteration=i)

    GracefulRunner(SERVICE, interval_s=15.0).run(tick)


if __name__ == "__main__":
    main()
