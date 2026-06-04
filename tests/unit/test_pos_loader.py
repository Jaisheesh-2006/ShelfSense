# PROMPT
# Task:
#   - Unit-test the POS CSV loader for the corrected 7-column dataset: timezone conversion and
#     grouping per-line-item rows into baskets keyed by (store_id, order_date, order_time).
# Context:
#   - The CSV cols: order_id,order_date,order_time,store_id,product_id,brand_name,total_amount.
#     order_id is per line item (NOT the basket key); a basket = rows sharing an order_time.
#     parse_pos_timestamp reads store-local DD-MM-YYYY + HH:MM:SS (IST) -> tz-aware UTC.
#     load_transactions sums total_amount, counts line_items, picks the dominant brand, mints an id.
# Constraints:
#   - Hermetic: build a tiny CSV via tmp_path; no dependency on the real docs/raw file or network.
# Output:
#   - Tests: IST->UTC is correct & tz-aware; rows sharing order_time merge into one basket even with
#     different order_ids; amount sums total_amount; line_items counts rows; dominant brand wins;
#     result sorted by time; rows with a bad date are skipped.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).
"""Unit tests for the POS sales CSV loader (IST->UTC + basket grouping by order_time)."""

from datetime import UTC

from shelfsense_common.pos_loader import load_transactions, parse_pos_timestamp

_HEADER = "order_id,order_date,order_time,store_id,product_id,brand_name,total_amount"


def _csv(tmp_path, *rows: str):
    p = tmp_path / "pos.csv"
    p.write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8")
    return p


def test_parse_pos_timestamp_ist_to_utc():
    ts = parse_pos_timestamp("10-04-2026", "19:21:55", "Asia/Kolkata")
    assert ts.tzinfo == UTC  # 19:21:55 IST is 13:51:55 UTC (-5:30)
    assert (ts.hour, ts.minute, ts.second) == (13, 51, 55)


def test_groups_line_items_into_baskets_by_order_time(tmp_path):
    csv = _csv(
        tmp_path,
        "1,10-04-2026,12:42:18,ST1008,100,Faces Canada,100",
        "2,10-04-2026,12:42:18,ST1008,101,Faces Canada,50",  # same time -> same basket
        "3,10-04-2026,12:42:18,ST1008,102,Good Vibes,25",  # same basket, minority brand
        "4,10-04-2026,13:00:00,ST1008,103,Lakme,200",  # different time -> different basket
    )
    txns = load_transactions(csv)
    assert len(txns) == 2  # two distinct order_times -> two baskets (order_id is NOT the key)
    basket1 = next(t for t in txns if t.line_items == 3)
    assert basket1.amount == 175.0  # total_amount summed across the 3 line items
    assert basket1.brand == "Faces Canada"  # dominant brand (2 of 3 rows)
    assert basket1.department == "makeup"  # derived from the dominant brand (ADR-0025)
    assert basket1.transaction_id == "ST1008_10-04-2026_12:42:18"
    assert (basket1.timestamp.hour, basket1.timestamp.minute) == (7, 12)  # 12:42 IST -> 07:12 UTC


def test_sorted_by_time(tmp_path):
    txns = load_transactions(
        _csv(
            tmp_path,
            "1,10-04-2026,13:00:00,ST1008,1,Lakme,200",
            "2,10-04-2026,12:00:00,ST1008,2,Faces Canada,100",
        )
    )
    assert [t.timestamp.hour for t in txns] == [6, 7]  # 12:00 IST (06:30 UTC) before 13:00 IST


def test_skips_bad_rows(tmp_path):
    txns = load_transactions(
        _csv(
            tmp_path,
            "1,not-a-date,12:00:00,ST1008,1,Faces Canada,100",  # bad date -> skip
            "2,10-04-2026,12:00:00,ST1008,2,Faces Canada,100",  # the only good one
        )
    )
    assert [t.transaction_id for t in txns] == ["ST1008_10-04-2026_12:00:00"]


def test_brand_optional_when_blank(tmp_path):
    txns = load_transactions(_csv(tmp_path, "1,10-04-2026,12:00:00,ST1008,1,,100"))
    assert txns[0].brand is None and txns[0].amount == 100.0
