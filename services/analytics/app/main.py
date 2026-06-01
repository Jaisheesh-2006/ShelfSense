"""analytics service — Phase 1 scaffold.

Responsibility (Phase 2): consume `track.updated`, build sessions, compute footfall, the
session-based funnel, dwell/zone engagement and anomalies; load the POS CSV for conversion; and
persist metrics to PostgreSQL. For now it boots, logs, and heartbeats. Real analytics in Phase 2.
"""

from __future__ import annotations

from shelfsense_common.config import get_settings
from shelfsense_common.logging import configure_logging, get_logger
from shelfsense_common.worker import GracefulRunner

SERVICE = "analytics"


def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE, settings.log_level)
    log = get_logger(SERVICE)
    log.info(
        "analytics_boot",
        consumes=settings.topic_tracks,
        produces=settings.topic_metrics,
        session_timeout_ms=settings.session_timeout_ms,
        note="Phase 1 scaffold — sessions/funnel/conversion arrive in Phase 2",
    )

    def tick(i: int) -> None:
        log.info("heartbeat", iteration=i)

    GracefulRunner(SERVICE, interval_s=15.0).run(tick)


if __name__ == "__main__":
    main()
