"""Database layer: engine, ORM models, and session helpers.

Persistence target for analytics output and the read surface for the API. Tables are created on
startup (create_all) for the challenge; a real deployment would use Alembic migrations.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from shelfsense_common.config import get_settings
from sqlalchemy import JSON, BigInteger, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class VisitSession(Base):
    """One customer visit (a session), written by the analytics service."""

    __tablename__ = "visit_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String, index=True)
    entry_zone: Mapped[str] = mapped_column(String)
    started_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    ended_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    funnel_stage: Mapped[str] = mapped_column(String, default="entered", index=True)
    total_dwell_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    is_staff: Mapped[bool] = mapped_column(default=False)


class Transaction(Base):
    """POS transaction loaded from the sales CSV (conversion numerator)."""

    __tablename__ = "transactions"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String)
    ts_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    line_items: Mapped[int] = mapped_column(Integer, default=0)
    gmv: Mapped[float] = mapped_column(Float, default=0.0)


class Metric(Base):
    """A computed business metric over a window, written by analytics."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    window_start_ms: Mapped[int] = mapped_column(BigInteger)
    window_end_ms: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float] = mapped_column(Float)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)


def _engine_url() -> str:
    # Use the psycopg (v3) driver explicitly.
    return get_settings().postgres_dsn.replace("postgresql://", "postgresql+psycopg://", 1)


_engine = create_engine(_engine_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """Create tables if they do not exist."""
    Base.metadata.create_all(_engine)


def ping_db() -> bool:
    """Return True if the database is reachable."""
    from sqlalchemy import text

    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
