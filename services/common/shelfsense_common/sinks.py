"""Event sinks — where emitted behavioural events are written/sent.

The detection layer emits `BehaviorEvent`s to one or more sinks:
- `JsonlEventSink` — newline-delimited JSON on disk (inspectable, crash-safe, exact replay).
- `HttpEventSink` — POSTs batches to the Intelligence API's `/events/ingest` (Slice 2.8 auto-feed,
  ADR-0015), so the running stack feeds itself with no manual replay. Idempotent ingest makes
  re-runs/restarts safe (ADR-0005 dropped the message broker; JSONL + idempotent POST gives the same
  durability without Kafka's weight).
- `FanOutSink` — writes to several sinks at once (JSONL for inspection + HTTP for the live API).
"""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType
from typing import Protocol

from shelfsense_common.contracts import BehaviorEvent


class EventSink(Protocol):
    """The minimal sink contract: a context manager that accepts `write(event)` and `flush()`."""

    def __enter__(self) -> EventSink: ...
    def __exit__(self, *exc: object) -> None: ...
    def write(self, event: BehaviorEvent) -> None: ...
    def flush(self) -> None: ...


class JsonlEventSink:
    """Append BehaviorEvents to a JSONL file, creating parent directories as needed.

    `truncate=True` starts a fresh file — correct for a single full detection pass (run_once), so a
    re-run re-exports rather than accumulating stale events from a prior run. The default (append)
    preserves streaming semantics where a run adds to an existing log.
    """

    def __init__(self, path: str | Path, truncate: bool = False) -> None:
        self.path = Path(path)
        self.truncate = truncate
        self._fh = None

    def __enter__(self) -> JsonlEventSink:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w" if self.truncate else "a", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write(self, event: BehaviorEvent) -> None:
        if self._fh is None:
            raise RuntimeError("JsonlEventSink must be used as a context manager")
        # model_dump_json serialises the tz-aware datetime as ISO-8601 and the enum as its value.
        self._fh.write(event.model_dump_json() + "\n")
        self._fh.flush()  # durability: each event is on disk before we process the next frame

    def flush(self) -> None:
        """Flush the file buffer. Each write already flushes for durability, so this is effectively
        a no-op; it exists so the sink satisfies the EventSink contract and `FanOutSink.flush()` can
        fan to every child uniformly (the per-camera incremental flush, ADR-0018)."""
        if self._fh is not None:
            self._fh.flush()


# Transport = "POST these JSON bytes to this URL"; injectable so the sink is testable offline.
Transport = Callable[[str, bytes], None]


def _default_transport(url: str, body: bytes) -> None:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (own API)
        response.read()


def _healthz_check(api_base: str) -> Callable[[], bool]:
    url = api_base.rstrip("/") + "/healthz"

    def check() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                return response.status == 200
        except Exception:
            return False

    return check


class HttpEventSink:
    """Buffer BehaviorEvents and POST them in batches to the API's `/events/ingest` (Slice 2.8).

    Closes the pipeline loop so `docker compose up` feeds the API with no manual replay. Design:
    - **Batched** to <=`batch_size` (the API's per-request cap); a final flush runs on exit.
    - **Idempotent-friendly:** ingest dedups by `event_id`, so a re-run/restart never double-counts.
    - **Resilient + non-fatal:** waits (bounded) for the API to be ready on enter, retries each POST
      with backoff, and on final failure logs a warning and drops the batch (the JSONL sink still
      keeps it for replay) — the detector never crashes because the API is slow/down.
    - **Testable:** the `transport` and `ready_check` are injectable, so batching/flush/retry are
      unit-tested with no network.
    """

    def __init__(
        self,
        api_base: str,
        *,
        batch_size: int = 500,
        wait_s: float = 60.0,
        poll_s: float = 1.0,
        max_retries: int = 5,
        backoff_s: float = 0.5,
        transport: Transport | None = None,
        ready_check: Callable[[], bool] | None = None,
        log: object | None = None,
    ) -> None:
        self._url = api_base.rstrip("/") + "/events/ingest"
        self._batch_size = max(1, batch_size)
        self._wait_s = wait_s
        self._poll_s = poll_s
        self._max_retries = max(1, max_retries)
        self._backoff_s = backoff_s
        self._transport = transport or _default_transport
        self._ready_check = ready_check if ready_check is not None else _healthz_check(api_base)
        self._log = log
        self._buffer: list[BehaviorEvent] = []
        self.posted = 0  # events successfully accepted by the transport

    def __enter__(self) -> HttpEventSink:
        self._wait_until_ready()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.flush()

    def write(self, event: BehaviorEvent) -> None:
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """POST whatever is buffered now (no-op if empty). Safe to call repeatedly mid-run — the
        detector calls it after each camera so the API populates progressively (ADR-0018), and it
        also runs on exit for the final partial batch."""
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        body = ('{"events":[' + ",".join(e.model_dump_json() for e in batch) + "]}").encode("utf-8")
        self._post_with_retry(body, len(batch))

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self._wait_s
        while True:
            try:
                if self._ready_check():
                    return
            except Exception:  # noqa: BLE001 — readiness probe must never raise
                pass
            if time.monotonic() >= deadline:
                self._warn("api_not_ready_proceeding", wait_s=self._wait_s)
                return
            time.sleep(self._poll_s)

    def _post_with_retry(self, body: bytes, count: int) -> None:
        for attempt in range(1, self._max_retries + 1):
            try:
                self._transport(self._url, body)
                self.posted += count
                return
            except Exception as exc:  # noqa: BLE001 — non-fatal; JSONL keeps the data for replay
                if attempt >= self._max_retries:
                    self._warn("ingest_post_failed", events=count, error=str(exc))
                    return
                time.sleep(self._backoff_s * attempt)

    def _warn(self, event: str, **fields: object) -> None:
        if self._log is not None and hasattr(self._log, "warning"):
            self._log.warning(event, **fields)


class FanOutSink:
    """Write each event to several sinks at once (e.g. JSONL for inspection + HTTP for the API).

    Uses an ExitStack so every child sink is entered/exited correctly (and partial-enter failures
    are unwound). `write()` fans to each child in order.
    """

    def __init__(self, sinks: Iterable[EventSink]) -> None:
        self._sinks: list[EventSink] = list(sinks)
        self._stack = ExitStack()

    def __enter__(self) -> FanOutSink:
        for sink in self._sinks:
            self._stack.enter_context(sink)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stack.close()

    def write(self, event: BehaviorEvent) -> None:
        for sink in self._sinks:
            sink.write(event)

    def flush(self) -> None:
        """Flush every child sink. Lets the caller push buffered events through mid-run (e.g. the
        detector's per-camera incremental flush) so the API populates progressively rather than only
        at the final exit (ADR-0018)."""
        for sink in self._sinks:
            sink.flush()
