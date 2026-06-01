"""Structured JSON logging shared by all services.

Usage:
    from shelfsense_common.logging import configure_logging, get_logger
    configure_logging("detector")
    log = get_logger(__name__)
    log.info("frame_processed", frame_id=42, detections=3)

Logs are JSON lines with a consistent shape (timestamp, level, service, event, + context).
Bind a correlation id once and it rides along: `log = log.bind(correlation_id=cid)`.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Configure stdlib + structlog to emit JSON. Call once at service startup."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Bind the service name to every log line for this process.
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
