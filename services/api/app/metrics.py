"""Prometheus metrics for the API service.

Exposes HTTP metrics (via middleware) plus business gauges that are refreshed from the database
at scrape time — so `/metrics` values genuinely reflect input and vary with it (integrity).
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select

from app.db import Metric, Transaction, VisitSession, get_session

HTTP_REQUESTS = Counter(
    "shelfsense_http_requests_total",
    "HTTP requests handled by the API.",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "shelfsense_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "path"],
)

SESSIONS_TOTAL = Gauge("shelfsense_sessions_total", "Number of recorded visit sessions.")
FOOTFALL_TOTAL = Gauge("shelfsense_footfall_total", "Customer sessions (footfall, staff excluded).")
TRANSACTIONS_TOTAL = Gauge("shelfsense_transactions_total", "POS transactions loaded.")
CONVERSION_RATE = Gauge("shelfsense_conversion_rate", "transactions / footfall (0..1).")
METRICS_ROWS = Gauge("shelfsense_metric_rows_total", "Rows in the metrics table.")


def refresh_business_gauges() -> None:
    """Recompute business gauges from the DB. Safe if tables are empty (returns zeros)."""
    try:
        with get_session() as s:
            sessions = s.scalar(select(func.count()).select_from(VisitSession)) or 0
            footfall = (
                s.scalar(
                    select(func.count())
                    .select_from(VisitSession)
                    .where(VisitSession.is_staff.is_(False))
                )
                or 0
            )
            txns = s.scalar(select(func.count()).select_from(Transaction)) or 0
            metric_rows = s.scalar(select(func.count()).select_from(Metric)) or 0
        SESSIONS_TOTAL.set(sessions)
        FOOTFALL_TOTAL.set(footfall)
        TRANSACTIONS_TOTAL.set(txns)
        METRICS_ROWS.set(metric_rows)
        CONVERSION_RATE.set(round(txns / footfall, 4) if footfall else 0.0)
    except Exception:
        # Never let metric scraping take down the endpoint.
        pass


def render_metrics() -> tuple[bytes, str]:
    refresh_business_gauges()
    return generate_latest(), CONTENT_TYPE_LATEST
