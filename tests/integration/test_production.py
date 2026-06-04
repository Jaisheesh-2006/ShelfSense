# PROMPT
# Task: Integration-test two production-readiness behaviours the SPEC (Part C) requires of the API:
#   (1) the per-request structured JSON log carries all six fields (trace_id, store_id, endpoint,
#       event_count, latency_ms, status_code), and (2) a DB-connectivity failure degrades to a
#       structured 503 (not a stack-traced 500).
# Context: the access log is emitted by the HTTP middleware in shelfsense_api.main as a JSON line;
#   trace_id rides via structlog contextvars, store_id comes from the path, and event_count is set
#   on request.state by the ingest handler. DB connectivity errors surface as SQLAlchemy
#   OperationalError and are mapped to 503 by an exception handler.
# Constraints: hermetic (SQLite via the `client` fixture); deterministic; no real Postgres. Assert
#   on the real rendered JSON (captured from stdout) so contextvars-bound fields are included;
#   simulate DB-down by making a repository call raise OperationalError.
# Output: pytest tests using the shared `client` fixture (tests/integration/conftest.py).

from __future__ import annotations

import json

from sqlalchemy.exc import OperationalError

REQUIRED_LOG_FIELDS = (
    "trace_id",
    "store_id",
    "endpoint",
    "event_count",
    "latency_ms",
    "status_code",
)


def _request_log_lines(captured_out: str) -> list[dict]:
    """Parse the JSON log lines and keep the per-request access logs."""
    lines = []
    for raw in captured_out.splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "request_completed":
            lines.append(obj)
    return lines


def test_request_log_has_all_six_fields_on_ingest(client, capsys) -> None:
    capsys.readouterr()  # flush startup/fixture logs so we only read this request's output

    resp = client.post("/events/ingest", json={"events": [{} for _ in range(3)]})
    assert resp.status_code == 200

    logs = _request_log_lines(capsys.readouterr().out)
    assert len(logs) == 1
    line = logs[0]
    for field in REQUIRED_LOG_FIELDS:
        assert field in line, f"missing {field} in request log: {line}"
    assert line["event_count"] == 3  # batch size surfaced from the ingest handler
    assert line["store_id"] is None  # /events/ingest has no store_id in its path
    assert line["endpoint"] == "/events/ingest"
    assert line["status_code"] == 200
    assert line["trace_id"]  # bound via contextvars, non-empty
    assert isinstance(line["latency_ms"], int)


def test_request_log_has_store_id_on_store_endpoint(client, capsys) -> None:
    capsys.readouterr()

    assert client.get("/stores/ST1008/metrics").status_code == 200

    logs = _request_log_lines(capsys.readouterr().out)
    assert len(logs) == 1
    line = logs[0]
    assert line["store_id"] == "ST1008"  # extracted from the path
    assert line["event_count"] is None  # a GET sets no event_count
    assert line["endpoint"] == "/stores/{store_id}/metrics"


def test_database_unavailable_returns_structured_503(client, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        # Mimics SQLAlchemy when the DB connection is refused/dropped mid-request.
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    # fetch_events is the first DB call /metrics makes; raise as if the DB went away.
    monkeypatch.setattr("shelfsense_api.routers.stores.fetch_events", _boom)

    resp = client.get("/stores/ST1008/metrics")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "database_unavailable"
    assert "message" in body["error"]  # human-readable, no stack trace leaked
