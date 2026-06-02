"""Load the POS sales CSV into validated `Transaction`s (the purchase side of conversion).

Pure and dependency-light (stdlib `csv` only — no pandas).

**Corrected-dataset format (2026-06-02, GROUND_TRUTH.md §2).** The CSV is 7 columns:
`order_id, order_date, order_time, store_id, product_id, brand_name, total_amount`. Unlike the old
export, **`order_id` is per line item** (1…101), so it is *not* the basket key — rows that share an
`order_time` form one basket. We therefore group to **one `Transaction` per
`(store_id, order_date, order_time)`** (24 baskets), with `amount` = Σ the basket's `total_amount`
and `brand` = the basket's dominant `brand_name`.

The CSV's `order_date` (DD-MM-YYYY) + `order_time` (HH:MM:SS) are **store-local (IST) with no zone
marker**. We attach the store timezone and convert to **UTC** so the 5-minute correlation window
compares with `BehaviorEvent` timestamps (also UTC). Getting this wrong shifts everything 5.5 h.

Malformed rows (missing date/time, unparseable numbers) are skipped, not fatal — the loader
degrades gracefully and returns what it could parse.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from shelfsense_common.contracts import Transaction
from shelfsense_common.departments import department_for

# CSV column names (corrected dataset — see docs/wiki/GROUND_TRUTH.md §2).
COL_ORDER_ID = "order_id"  # per-line-item counter now, NOT the basket key
COL_DATE = "order_date"  # DD-MM-YYYY
COL_TIME = "order_time"  # HH:MM:SS (24h) — the basket key (with store_id + date)
COL_STORE = "store_id"
COL_BRAND = "brand_name"
COL_AMOUNT = "total_amount"  # per-line-item sale value; basket value = sum of these

_DATETIME_FMT = "%d-%m-%Y %H:%M:%S"


def parse_pos_timestamp(order_date: str, order_time: str, store_tz: str) -> datetime:
    """`DD-MM-YYYY` + `HH:MM:SS` interpreted in `store_tz` -> tz-aware **UTC** datetime. Pure."""
    local = datetime.strptime(f"{order_date.strip()} {order_time.strip()}", _DATETIME_FMT)
    return local.replace(tzinfo=ZoneInfo(store_tz)).astimezone(UTC)


def _to_float(value: str | None) -> float:
    try:
        return float((value or "").strip())
    except ValueError:
        return 0.0


def load_transactions(csv_path: str | Path, store_tz: str = "Asia/Kolkata") -> list[Transaction]:
    """Parse the sales CSV into one `Transaction` per basket (`store_id`+`order_date`+`order_time`).

    `amount` = sum of the basket's `total_amount` rows; `brand` = the basket's most common
    `brand_name`; `line_items` = number of rows in the basket; `transaction_id` is a stable
    synthesized key. Rows with an unparseable date/time are skipped. Result is sorted by timestamp.
    """
    grouped: dict[tuple[str, str, str], dict] = {}
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            date_s = (row.get(COL_DATE) or "").strip()
            time_s = (row.get(COL_TIME) or "").strip()
            try:
                ts = parse_pos_timestamp(date_s, time_s, store_tz)
            except (ValueError, KeyError, TypeError):
                continue  # unparseable date/time -> skip this row, don't crash the load
            store = (row.get(COL_STORE) or "").strip()
            key = (store, date_s, time_s)
            brand = (row.get(COL_BRAND) or "").strip() or None
            rec = grouped.get(key)
            if rec is None:
                grouped[key] = {
                    "store": store,
                    "timestamp": ts,
                    "amount": _to_float(row.get(COL_AMOUNT)),
                    "brands": Counter([brand] if brand else []),
                    "line_items": 1,
                }
            else:
                rec["amount"] += _to_float(row.get(COL_AMOUNT))
                rec["line_items"] += 1
                if brand:
                    rec["brands"][brand] += 1

    transactions = []
    for (store, date_s, time_s), rec in grouped.items():
        brand = rec["brands"].most_common(1)[0][0] if rec["brands"] else None
        transactions.append(
            Transaction(
                transaction_id=f"{store}_{date_s}_{time_s}",
                timestamp=rec["timestamp"],
                amount=round(rec["amount"], 2),
                brand=brand,
                department=department_for(brand),
                line_items=rec["line_items"],
            )
        )
    transactions.sort(key=lambda t: t.timestamp)
    return transactions
