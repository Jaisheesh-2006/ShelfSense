"""Event stream client for Redpanda/Kafka.

Thin wrapper that publishes our `Event` envelopes as JSON. The Kafka library is imported lazily
so services that don't stream (e.g. the API) don't need it installed. Streaming services list
`confluent-kafka` in their own requirements.

Events are keyed (e.g. by camera_id) so all events for one key land on the same partition and stay
ordered — important for tracking and idempotent downstream processing.
"""
from __future__ import annotations

from types import TracebackType
from typing import Any

from shelfsense_common.contracts.events import Event
from shelfsense_common.logging import get_logger

_log = get_logger("stream")


class EventProducer:
    """Publishes `Event` objects to the stream. Use as a context manager so it flushes on exit."""

    def __init__(self, bootstrap_servers: str, client_id: str = "shelfsense") -> None:
        try:
            from confluent_kafka import Producer
        except ImportError as exc:  # pragma: no cover - clear failure if dep missing
            raise RuntimeError(
                "confluent-kafka is required to publish events; add it to the service requirements"
            ) from exc

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                # Exactly-once-ish producer semantics: no duplicates on retry, ordered per key.
                "enable.idempotence": True,
            }
        )

    def _on_delivery(self, err: Any, msg: Any) -> None:
        if err is not None:
            _log.error("publish_failed", topic=msg.topic(), error=str(err))

    def publish(self, topic: str, event: Event[Any], key: str | None = None) -> None:
        """Queue an event for sending. Non-blocking; call flush() to ensure delivery."""
        self._producer.produce(
            topic,
            value=event.model_dump_json().encode("utf-8"),
            key=key.encode("utf-8") if key else None,
            on_delivery=self._on_delivery,
        )
        # Serve delivery callbacks without blocking.
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        """Block until queued messages are delivered. Returns # still in queue (0 = all sent)."""
        return self._producer.flush(timeout)

    def __enter__(self) -> EventProducer:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        remaining = self.flush()
        if remaining:
            _log.warning("undelivered_on_close", count=remaining)
