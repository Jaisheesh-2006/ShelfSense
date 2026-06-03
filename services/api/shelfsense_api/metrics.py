"""Prometheus metrics for the API service.

Exposes HTTP metrics (via middleware) plus business gauges refreshed from the database at scrape
time — so `/metrics` genuinely reflects ingested input and varies with it (integrity). Gauges are
computed from the ingested `behavior_events` (the Slice 2.6 source of truth), reusing the same
`analytics` the API serves so the numbers can never diverge.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from shelfsense_common.analytics import compute_store_metrics
from shelfsense_common.config import get_settings
from shelfsense_common.stores import DEFAULT_STORE_ID
from sqlalchemy import func, select

from shelfsense_api.db import BehaviorEventRow, Transaction, get_session
from shelfsense_api.repository import fetch_events, fetch_transactions

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

EVENTS_TOTAL = Gauge("shelfsense_events_total", "Behavioural events ingested.")
UNIQUE_VISITORS = Gauge("shelfsense_unique_visitors", "Distinct non-staff visitors.")
TRANSACTIONS_TOTAL = Gauge("shelfsense_transactions_total", "POS transactions loaded.")
CONVERSION_RATE = Gauge("shelfsense_conversion_rate", "converted / unique visitors (0..1).")


def refresh_business_gauges() -> None:
    """Recompute business gauges from the DB. Safe if tables are empty (returns zeros)."""
    try:
        settings = get_settings()
        with get_session() as s:
            events_total = s.scalar(select(func.count()).select_from(BehaviorEventRow)) or 0
            txns_total = s.scalar(select(func.count()).select_from(Transaction)) or 0
            # Headline business gauges reflect the conversion store (the one with POS).
            events = fetch_events(s, DEFAULT_STORE_ID)
            txns = fetch_transactions(s)
        metrics = compute_store_metrics(
            events,
            txns,
            store_tz=settings.store_timezone,
            window_ms=settings.pos_correlation_window_ms,
            low_sample_threshold=settings.conversion_low_sample_threshold,
        )
        EVENTS_TOTAL.set(events_total)
        TRANSACTIONS_TOTAL.set(txns_total)
        UNIQUE_VISITORS.set(metrics.unique_visitors)
        CONVERSION_RATE.set(metrics.conversion_rate)
    except Exception:
        # Never let metric scraping take down the endpoint.
        pass


def render_metrics() -> tuple[bytes, str]:
    refresh_business_gauges()
    return generate_latest(), CONTENT_TYPE_LATEST
