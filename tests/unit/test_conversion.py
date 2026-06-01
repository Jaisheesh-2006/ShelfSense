# PROMPT
# Task:
#   - Unit-test the conversion correlation: the 5-minute billing-before-sale rule, converted/abandon
#     sets, the conversion rate, the low-sample flag, and the POS day-metrics.
# Context:
#   - correlate_conversions: a billing presence at t is converted if a transaction T satisfies
#     t <= T <= t + window_ms; billing visitors with no match are abandons; rate = converted/unique.
#     data_confidence is "low" when unique visitors < threshold. pos_day_metrics gives count/GMV.
# Constraints:
#   - Pure logic only: construct BillingPresence + Transaction objects directly (no CSV, no IO).
# Output:
#   - Tests: match at the window edge, miss one ms past it; converted/abandon split; rate math;
#     empty presences -> 0 + low confidence; confidence flips to "ok" above threshold; day-metrics.
"""Unit tests for the pure conversion correlation + day metrics."""

from datetime import UTC, datetime, timedelta

from shelfsense_common.contracts import Transaction
from shelfsense_common.conversion import (
    BillingPresence,
    correlate_conversions,
    pos_day_metrics,
)

T0 = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)


def _txn(tid: str, at: datetime, amount: float = 100.0, dept: str = "makeup") -> Transaction:
    return Transaction(transaction_id=tid, timestamp=at, amount=amount, department=dept)


def test_match_at_window_edge_and_miss_just_past():
    presence = BillingPresence("VIS_a", T0)
    at_edge = [_txn("o1", T0 + timedelta(minutes=5))]  # exactly 5 min after -> converted
    just_past = [_txn("o2", T0 + timedelta(minutes=5, milliseconds=1))]  # 1 ms too late -> miss
    assert correlate_conversions([presence], at_edge, {"VIS_a"}).converted_visitor_ids == {"VIS_a"}
    assert correlate_conversions([presence], just_past, {"VIS_a"}).converted_visitor_ids == set()


def test_sale_before_presence_does_not_convert():
    presence = BillingPresence("VIS_a", T0)
    before = [_txn("o1", T0 - timedelta(minutes=1))]  # sale BEFORE presence -> not converted
    assert correlate_conversions([presence], before, {"VIS_a"}).converted_visitor_ids == set()


def test_converted_and_abandoned_split_and_rate():
    presences = [
        BillingPresence("VIS_buyer", T0),
        BillingPresence("VIS_leaver", T0 + timedelta(hours=1)),  # no sale near this time
    ]
    txns = [_txn("o1", T0 + timedelta(minutes=2))]  # only the buyer has a following sale
    result = correlate_conversions(presences, txns, {"VIS_buyer", "VIS_leaver"})
    assert result.converted_visitor_ids == {"VIS_buyer"}
    assert result.abandoned_visitor_ids == {"VIS_leaver"}
    assert result.conversion_rate == 0.5  # 1 converted / 2 unique


def test_empty_billing_is_honest_zero_low_confidence():
    result = correlate_conversions([], [_txn("o1", T0)], {"VIS_a", "VIS_b"})
    assert result.conversion_rate == 0.0
    assert result.converted_visitor_ids == set()
    assert result.data_confidence == "low"  # 2 unique < default threshold 20


def test_confidence_ok_above_threshold():
    result = correlate_conversions([], [], {"VIS_a", "VIS_b"}, low_sample_threshold=2)
    assert result.data_confidence == "ok"  # 2 unique >= threshold 2


def test_no_unique_visitors_does_not_divide_by_zero():
    assert correlate_conversions([], [], set()).conversion_rate == 0.0


def test_pos_day_metrics():
    txns = [
        _txn("o1", T0, amount=100.0, dept="makeup"),
        _txn("o2", T0 + timedelta(hours=1), amount=300.0, dept="skin"),
        _txn("o3", T0 + timedelta(hours=1), amount=200.0, dept="makeup"),
    ]
    m = pos_day_metrics(txns)
    assert m["transaction_count"] == 3
    assert m["total_gmv"] == 600.0
    assert m["avg_basket"] == 200.0
    assert m["top_department"] == "makeup"  # 2 of 3 orders


def test_pos_day_metrics_empty():
    m = pos_day_metrics([])
    assert m["transaction_count"] == 0 and m["total_gmv"] == 0.0 and m["peak_hour"] is None
