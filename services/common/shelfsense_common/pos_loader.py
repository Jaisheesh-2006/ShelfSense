"""Load the Brigade POS sales CSV into validated `Transaction`s (the purchase side of conversion).

Pure and dependency-light (stdlib `csv` only — no pandas). The CSV grain is **one line item per
row** (101 rows); a basket is all rows sharing an `order_id`, so we group to **one `Transaction`
per distinct `order_id`** (24 of them) with `amount` = sum of the order's `total_amount`.

The CSV's `order_date` (DD-MM-YYYY) + `order_time` (HH:MM:SS) are **store-local (IST) with no zone
marker**. We attach the store timezone and convert to **UTC** so the 5-minute correlation window
compares with `BehaviorEvent` timestamps (also UTC). Getting this wrong shifts everything 5.5 h.

Malformed rows (missing id/date/time, unparseable numbers) are skipped, not fatal — the loader
degrades gracefully and returns what it could parse.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from shelfsense_common.contracts import Transaction

# CSV column names (see docs/wiki/GROUND_TRUTH.md §2).
COL_ORDER_ID = "order_id"
COL_INVOICE = "invoice_number"
COL_DATE = "order_date"  # DD-MM-YYYY
COL_TIME = "order_time"  # HH:MM:SS (24h)
COL_AMOUNT = "GMV"  # gross merchandise value (headline retail sales figure; day total ≈ ₹44,920)
COL_DEPT = "dep_name"

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
    """Parse the sales CSV into one `Transaction` per distinct `order_id`, sorted by time.

    `amount` = sum of the order's GMV rows; `department`/`invoice_number` from the order's first
    row; `line_items` = number of rows in the order. Rows that can't be parsed are skipped.
    """
    grouped: dict[str, dict] = {}
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            order_id = (row.get(COL_ORDER_ID) or "").strip()
            if not order_id:
                continue
            try:
                ts = parse_pos_timestamp(row[COL_DATE], row[COL_TIME], store_tz)
            except (ValueError, KeyError, TypeError):
                continue  # unparseable date/time -> skip this row, don't crash the load
            rec = grouped.get(order_id)
            if rec is None:
                grouped[order_id] = {
                    "invoice": (row.get(COL_INVOICE) or "").strip() or None,
                    "timestamp": ts,
                    "amount": _to_float(row.get(COL_AMOUNT)),
                    "department": (row.get(COL_DEPT) or "").strip() or None,
                    "line_items": 1,
                }
            else:
                rec["amount"] += _to_float(row.get(COL_AMOUNT))
                rec["line_items"] += 1
                rec["timestamp"] = min(rec["timestamp"], ts)  # order time = its earliest line

    transactions = [
        Transaction(
            transaction_id=order_id,
            invoice_number=rec["invoice"],
            timestamp=rec["timestamp"],
            amount=round(rec["amount"], 2),
            department=rec["department"],
            line_items=rec["line_items"],
        )
        for order_id, rec in grouped.items()
    ]
    transactions.sort(key=lambda t: t.timestamp)
    return transactions
