"""POS (point-of-sale) transaction contract — the domain value object for a real store sale.

This is the **purchase** side of the North Star (conversion = converted ÷ unique visitors). The
detection pipeline never reads sales; this contract + the loader (pos_loader.py) turn the POS sales
CSV into validated `Transaction`s that the conversion logic (conversion.py) correlates with
billing-zone presence.

Grain (corrected dataset, 2026-06-02 — see GROUND_TRUTH.md §2): the 7-column CSV's `order_id` is now
**per line item**, so a **basket = all rows sharing an `order_time`** (24 of them). One
`Transaction` = one basket: `amount` = sum of the basket's `total_amount`; `brand` = the basket's
dominant `brand_name` (the old `dep_name`/`department` column no longer exists).

Note: this is a *domain/loader* value object, distinct from the SQLAlchemy `Transaction` ORM row in
services/api/shelfsense_api/db.py (persistence). The API maps loader <-> ORM in repository.py.

Timestamps are timezone-aware UTC — the same clock `BehaviorEvent.timestamp` uses — so the 5-minute
correlation window compares like-with-like (the CSV's store-local IST times are converted on load).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Transaction(BaseModel):
    """One POS sale (a basket), keyed by a synthesized `transaction_id` (store+date+order_time)."""

    model_config = ConfigDict(frozen=True)

    transaction_id: str  # stable id for the basket (store_id + order_date + order_time)
    timestamp: datetime  # tz-aware UTC, from order_date + order_time (store-local) -> UTC
    amount: float = Field(ge=0.0)  # basket value = sum of the basket's `total_amount` rows
    brand: str | None = None  # dominant `brand_name` of the basket (e.g. Faces Canada/Good Vibes)
    department: str = "other"  # category derived from `brand` (see departments.py; ADR-0025)
    line_items: int = Field(default=1, ge=1)  # number of CSV rows that make up this basket

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_utc(cls, v: datetime) -> datetime:
        """Reject naive datetimes and normalise to UTC (matches BehaviorEvent's rule)."""
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v.astimezone(UTC)
