"""Event sinks — where emitted behavioural events are written.

For the demo the detection layer writes newline-delimited JSON (JSONL) that the Intelligence API
ingests via POST in Slice 2.6 (ADR-0005 dropped the message broker; JSONL + idempotent ingest
gives durability and exact replay without the operational weight of Kafka).

`JsonlEventSink` is intentionally tiny: append one `BehaviorEvent` per line. JSONL is chosen over a
JSON array so the file is append-only, crash-safe (a partial last line is the worst case), and
streamable line-by-line on ingest.
"""
from __future__ import annotations

from pathlib import Path
from types import TracebackType

from shelfsense_common.contracts import BehaviorEvent


class JsonlEventSink:
    """Append BehaviorEvents to a JSONL file, creating parent directories as needed."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fh = None

    def __enter__(self) -> JsonlEventSink:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
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
