"""Conversion correlation — match billing-zone shoppers to real POS sales (North Star numerator).

Pure logic (no IO, no model), so it is fully unit-testable and the Slice 2.6 API reuses it verbatim.

The rule (SPEC / BUSINESS_RULES): there's no customer id, so we correlate by **time + store**. A
visitor in the billing zone within the **5 minutes before a transaction** counts as *converted*;
a billing-zone visitor with no following sale in that window is an *abandon*. Conversion rate =
converted ÷ unique visitors (staff already excluded upstream).

Honest-data note: on the 2-minute clip no customer reaches the checkout and no sale lands in the
window, so this returns 0 with `data_confidence="low"` — truthful, not a bug. The same function,
given real billing presence near a sale, returns a real conversion (see scripts/demo_conversion.py).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from shelfsense_common.contracts import Transaction

DEFAULT_WINDOW_MS = 300_000  # 5 minutes
DEFAULT_LOW_SAMPLE = 20  # < this many unique visitors -> data_confidence "low"


@dataclass(frozen=True)
class BillingPresence:
    """A (non-staff) visitor observed in the billing zone at a point in time (UTC)."""

    visitor_id: str
    timestamp: datetime


@dataclass(frozen=True)
class ConversionResult:
    unique_visitors: int
    converted_visitor_ids: set[str] = field(default_factory=set)
    abandoned_visitor_ids: set[str] = field(default_factory=set)
    conversion_rate: float = 0.0
    data_confidence: str = "low"  # "low" when the sample is too small to trust the rate


def correlate_conversions(
    billing_presences: Iterable[BillingPresence],
    transactions: Iterable[Transaction],
    unique_visitor_ids: Iterable[str],
    window_ms: int = DEFAULT_WINDOW_MS,
    low_sample_threshold: int = DEFAULT_LOW_SAMPLE,
) -> ConversionResult:
    """Correlate billing presence with sales by the time-window rule; compute the conversion rate.

    A presence at time `t` is converted if any transaction `T` satisfies `t <= T <= t + window_ms`
    (i.e. the visitor was at billing within `window_ms` *before* the sale). A visitor converts if
    ANY of their presences matches; billing visitors with no match are abandons.
    """
    presences = list(billing_presences)
    txns = list(transactions)
    unique = set(unique_visitor_ids)

    converted: set[str] = set()
    billing_visitors: set[str] = set()
    for p in presences:
        billing_visitors.add(p.visitor_id)
        for txn in txns:
            delta_ms = (txn.timestamp - p.timestamp).total_seconds() * 1000.0
            if 0.0 <= delta_ms <= window_ms:
                converted.add(p.visitor_id)
                break

    abandoned = billing_visitors - converted
    rate = round(len(converted) / len(unique), 4) if unique else 0.0
    confidence = "low" if len(unique) < low_sample_threshold else "ok"
    return ConversionResult(
        unique_visitors=len(unique),
        converted_visitor_ids=converted,
        abandoned_visitor_ids=abandoned,
        conversion_rate=rate,
        data_confidence=confidence,
    )


def pos_day_metrics(
    transactions: Iterable[Transaction], store_tz: str = "Asia/Kolkata"
) -> dict:
    """Free day-level KPIs from the sales file (independent of the video window).

    Returns transaction_count, total_gmv, avg_basket, top_brand, top_department, and peak_hour
    (store-local). `top_brand`/`top_department` are by basket count (the busiest, not the richest);
    department is derived from the basket's dominant brand (departments.py, ADR-0025).
    """
    txns = list(transactions)
    count = len(txns)
    if count == 0:
        return {
            "transaction_count": 0, "total_gmv": 0.0, "avg_basket": 0.0,
            "top_brand": None, "top_department": None, "peak_hour": None,
        }
    total = round(sum(t.amount for t in txns), 2)
    local = ZoneInfo(store_tz)
    peak_hour = Counter(t.timestamp.astimezone(local).hour for t in txns).most_common(1)[0][0]
    brands = Counter(t.brand for t in txns if t.brand)
    top_brand = brands.most_common(1)[0][0] if brands else None
    # Department rollup excludes the catch-all "other" so a meaningful category wins (e.g. makeup),
    # not the own-label/unmapped bucket; falls back to None only if every basket is "other".
    depts = Counter(t.department for t in txns if t.department and t.department != "other")
    top_department = depts.most_common(1)[0][0] if depts else None
    return {
        "transaction_count": count,
        "total_gmv": total,
        "avg_basket": round(total / count, 2),
        "top_brand": top_brand,
        "top_department": top_department,
        "peak_hour": peak_hour,  # store-local hour (0-23) with the most sales
    }
