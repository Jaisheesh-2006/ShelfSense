"""Database layer: engine, ORM models, and session helpers.

Persistence target for ingested behavioural events + POS sales, and the read surface the API
computes metrics from. Tables are created on startup (create_all) for the challenge; a real
deployment would use Alembic migrations. `configure_engine()` lets tests bind a throwaway SQLite
engine without touching Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from shelfsense_common.config import get_settings
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class BehaviorEventRow(Base):
    """One ingested behavioural event (the prescribed flat schema, EVENT_SCHEMA.md).

    `event_id` is the primary key, which makes ingest idempotent: re-POSTing the same event is a
    no-op (ADR-0013). Timestamps are stored as epoch-ms (`ts_ms`) for cheap range queries.
    """

    __tablename__ = "behavior_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    camera_id: Mapped[str] = mapped_column(String)
    visitor_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    zone_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dwell_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    queue_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)


class VisitSession(Base):
    """One customer visit (a session). Retained for future analytics writes; not used by 2.6."""

    __tablename__ = "visit_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String, index=True)
    entry_zone: Mapped[str] = mapped_column(String)
    started_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    ended_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    funnel_stage: Mapped[str] = mapped_column(String, default="entered", index=True)
    total_dwell_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)


class Transaction(Base):
    """POS transaction (a basket) loaded from the sales CSV (conversion numerator).

    `order_id` is the synthesized basket key (store_id + order_date + order_time); `gmv` stores the
    basket's summed `total_amount`; `brand` is the basket's dominant `brand_name` (the old
    `dep_name`/`department` column is gone from the corrected dataset).
    """

    __tablename__ = "transactions"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    line_items: Mapped[int] = mapped_column(Integer, default=0)
    gmv: Mapped[float] = mapped_column(Float, default=0.0)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)


class Metric(Base):
    """A computed business metric over a window, written by analytics."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    window_start_ms: Mapped[int] = mapped_column(BigInteger)
    window_end_ms: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float] = mapped_column(Float)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)


def _default_url() -> str:
    # Use the psycopg (v3) driver explicitly.
    return get_settings().postgres_dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _build_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


# Engine is built lazily on first use (not at import) so that importing the app does not require the
# Postgres driver — tests rebind to SQLite via `configure_engine()` before anything connects.
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_engine() -> None:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine(_default_url())
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)


def configure_engine(url: str) -> None:
    """Rebind the engine/session factory to `url` (used by tests for a SQLite database)."""
    global _engine, _SessionLocal
    _engine = _build_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """Create tables if they do not exist."""
    _ensure_engine()
    assert _engine is not None
    Base.metadata.create_all(_engine)


def ping_db() -> bool:
    """Return True if the database is reachable."""
    from sqlalchemy import text

    try:
        _ensure_engine()
        assert _engine is not None
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@contextmanager
def get_session() -> Iterator[Session]:
    _ensure_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
