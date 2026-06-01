"""POS (point-of-sale) transaction contract — the domain value object for a real store sale.

This is the **purchase** side of the North Star (conversion = converted ÷ unique visitors). The
detection pipeline never reads sales; this contract + the loader (pos_loader.py) turn the Brigade
sales CSV into validated `Transaction`s that the conversion logic (conversion.py) correlates with
billing-zone presence. One `Transaction` = one distinct `order_id` (basket), not one line item.

Note: this is a *domain/loader* value object, distinct from the SQLAlchemy `Transaction` ORM row in
services/api/app/db.py (persistence). Slice 2.6's API maps loader -> ORM; they are different layers.

Timestamps are timezone-aware UTC — the same clock `BehaviorEvent.timestamp` uses — so the 5-minute
correlation window compares like-with-like (the CSV's store-local IST times are converted on load).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Transaction(BaseModel):
    """One POS sale (a basket), keyed by `transaction_id` (the CSV `order_id`)."""

    model_config = ConfigDict(frozen=True)

    transaction_id: str  # distinct order_id from the CSV
    invoice_number: str | None = None  # human-facing invoice id (e.g. ML0426KAP0001358)
    timestamp: datetime  # tz-aware UTC, from order_date + order_time (store-local) -> UTC
    amount: float = Field(ge=0.0)  # basket value = sum of the order's GMV (gross merchandise value)
    department: str | None = None  # dep_name of the order's primary line (makeup/skin/…)
    line_items: int = Field(default=1, ge=1)  # number of CSV rows that make up this order

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_utc(cls, v: datetime) -> datetime:
        """Reject naive datetimes and normalise to UTC (matches BehaviorEvent's rule)."""
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v.astimezone(UTC)
