"""Repository: the only place that maps Pydantic contracts ↔ ORM rows and touches the DB.

Keeping persistence here (not in route handlers or in the pure `analytics`/`conversion` modules)
preserves the layering: routers orchestrate, `analytics` computes, this module reads/writes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from shelfsense_common.contracts import BehaviorEvent, EventMetadata, Transaction
from shelfsense_common.departments import department_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shelfsense_api.db import BehaviorEventRow
from shelfsense_api.db import Transaction as TxnRow


def _ts_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _row_from_event(e: BehaviorEvent) -> BehaviorEventRow:
    return BehaviorEventRow(
        event_id=e.event_id,
        store_id=e.store_id,
        camera_id=e.camera_id,
        visitor_id=e.visitor_id,
        event_type=e.event_type.value,
        ts_ms=_ts_ms(e.timestamp),
        zone_id=e.zone_id,
        dwell_ms=e.dwell_ms,
        is_staff=e.is_staff,
        confidence=e.confidence,
        queue_depth=e.metadata.queue_depth,
    )


def _event_from_row(r: BehaviorEventRow) -> BehaviorEvent:
    return BehaviorEvent(
        event_id=r.event_id,
        store_id=r.store_id,
        camera_id=r.camera_id,
        visitor_id=r.visitor_id,
        event_type=r.event_type,
        timestamp=datetime.fromtimestamp(r.ts_ms / 1000, tz=UTC),
        zone_id=r.zone_id,
        dwell_ms=r.dwell_ms,
        is_staff=r.is_staff,
        confidence=r.confidence,
        metadata=EventMetadata(queue_depth=r.queue_depth),
    )


def insert_events_dedup(session: Session, events: list[BehaviorEvent]) -> tuple[int, int]:
    """Insert events idempotently by `event_id`. Returns (accepted_new, duplicates).

    Dedup happens at two levels: within the batch (repeated ids in one POST) and against the DB
    (events already stored — so re-POSTing is a safe no-op). A concurrent inserter racing us is
    caught via IntegrityError and resolved per-row, never double-counting.
    """
    if not events:
        return 0, 0

    unique: dict[str, BehaviorEvent] = {}
    within_batch_dupes = 0
    for e in events:
        if e.event_id in unique:
            within_batch_dupes += 1
        else:
            unique[e.event_id] = e

    ids = list(unique)
    existing = set(
        session.scalars(
            select(BehaviorEventRow.event_id).where(BehaviorEventRow.event_id.in_(ids))
        ).all()
    )
    candidates = [e for eid, e in unique.items() if eid not in existing]

    try:
        session.add_all([_row_from_event(e) for e in candidates])
        session.commit()
        accepted = len(candidates)
    except IntegrityError:
        # Lost a race for some ids; resolve row-by-row so the result stays idempotent.
        session.rollback()
        accepted = 0
        for e in candidates:
            if session.get(BehaviorEventRow, e.event_id) is not None:
                continue
            session.add(_row_from_event(e))
            try:
                session.commit()
                accepted += 1
            except IntegrityError:
                session.rollback()

    duplicates = within_batch_dupes + (len(unique) - accepted)
    return accepted, duplicates


def fetch_events(session: Session, store_id: str) -> list[BehaviorEvent]:
    """All stored events for a store, oldest first."""
    rows = session.scalars(
        select(BehaviorEventRow)
        .where(BehaviorEventRow.store_id == store_id)
        .order_by(BehaviorEventRow.ts_ms)
    ).all()
    return [_event_from_row(r) for r in rows]


def latest_event_ms(session: Session, store_id: str) -> int | None:
    """Epoch-ms of the most recent event for a store (None if none). Used by /health."""
    from sqlalchemy import func

    return session.scalar(
        select(func.max(BehaviorEventRow.ts_ms)).where(BehaviorEventRow.store_id == store_id)
    )


def latest_event_ms_by_store(session: Session) -> dict[str, int]:
    """Map of store_id -> epoch-ms of its most recent event (one row per store with events)."""
    from sqlalchemy import func

    rows = session.execute(
        select(BehaviorEventRow.store_id, func.max(BehaviorEventRow.ts_ms)).group_by(
            BehaviorEventRow.store_id
        )
    ).all()
    return dict(rows)


def upsert_transactions(session: Session, txns: Iterable[Transaction]) -> int:
    """Idempotently upsert POS transactions by basket id. Returns the number processed."""
    count = 0
    for t in txns:
        row = session.get(TxnRow, t.transaction_id)
        if row is None:
            row = TxnRow(order_id=t.transaction_id)
            session.add(row)
        row.ts_ms = _ts_ms(t.timestamp)
        row.line_items = t.line_items
        row.gmv = t.amount
        row.brand = t.brand
        count += 1
    session.commit()
    return count


def fetch_transactions(session: Session) -> list[Transaction]:
    """All POS transactions as domain objects (for conversion + day metrics)."""
    rows = session.scalars(select(TxnRow)).all()
    return [
        Transaction(
            transaction_id=r.order_id,
            timestamp=datetime.fromtimestamp(r.ts_ms / 1000, tz=UTC),
            amount=r.gmv,
            brand=r.brand,
            department=department_for(r.brand),
            line_items=r.line_items or 1,
        )
        for r in rows
    ]
