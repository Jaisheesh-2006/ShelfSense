# PROMPT
# Task:
#   - Unit-test the POS CSV loader: timezone conversion and grouping line items into orders.
# Context:
#   - parse_pos_timestamp reads store-local DD-MM-YYYY + HH:MM:SS (IST) and returns tz-aware UTC.
#     load_transactions groups CSV rows by order_id into one Transaction (amount = sum of GMV,
#     line_items = row count, timestamp = the order's earliest line), skipping unparseable rows.
# Constraints:
#   - Hermetic: build a tiny CSV via tmp_path; no dependency on the real docs/raw file or network.
# Output:
#   - Tests: IST->UTC is correct & tz-aware; two orders dedup from three line rows; amount sums GMV;
#     line_items counts rows; result sorted by time; rows with no order_id / bad date are skipped.
"""Unit tests for the POS sales CSV loader (IST->UTC + order grouping)."""

from datetime import UTC

from shelfsense_common.pos_loader import load_transactions, parse_pos_timestamp

_HEADER = "order_id,invoice_number,order_date,order_time,GMV,dep_name"


def _csv(tmp_path, *rows: str):
    p = tmp_path / "pos.csv"
    p.write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8")
    return p


def test_parse_pos_timestamp_ist_to_utc():
    ts = parse_pos_timestamp("10-04-2026", "19:21:55", "Asia/Kolkata")
    assert ts.tzinfo == UTC  # 19:21:55 IST is 13:51:55 UTC (-5:30)
    assert (ts.hour, ts.minute, ts.second) == (13, 51, 55)


def test_groups_line_items_into_orders(tmp_path):
    csv = _csv(
        tmp_path,
        "1,INV1,10-04-2026,12:00:00,100,makeup",
        "1,INV1,10-04-2026,12:00:30,50,makeup",  # same order -> merge
        "2,INV2,10-04-2026,13:00:00,200,skin",
    )
    txns = load_transactions(csv)
    assert len(txns) == 2  # two distinct order_ids
    order1 = next(t for t in txns if t.transaction_id == "1")
    assert order1.amount == 150.0 and order1.line_items == 2  # GMV summed, 2 rows
    assert order1.department == "makeup"
    assert (order1.timestamp.hour, order1.timestamp.minute) == (6, 30)  # 12:00 IST -> 06:30 UTC


def test_sorted_by_time(tmp_path):
    txns = load_transactions(
        _csv(
            tmp_path,
            "2,INV2,10-04-2026,13:00:00,200,skin",
            "1,INV1,10-04-2026,12:00:00,100,makeup",
        )
    )
    assert [t.transaction_id for t in txns] == ["1", "2"]  # earliest first


def test_skips_bad_rows(tmp_path):
    txns = load_transactions(
        _csv(
            tmp_path,
            ",INV0,10-04-2026,12:00:00,100,makeup",  # no order_id -> skip
            "9,INV9,not-a-date,12:00:00,100,makeup",  # bad date -> skip
            "1,INV1,10-04-2026,12:00:00,100,makeup",  # the only good one
        )
    )
    assert [t.transaction_id for t in txns] == ["1"]
