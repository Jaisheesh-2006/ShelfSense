"""Startup POS load: read the sales CSV into Postgres so conversion can join against real sales.

Runs once in the API lifespan. Idempotent (upsert by order id) and defensive — a missing or
unreadable CSV logs a warning and leaves the API up returning honest zeros, never crashing.
"""

from __future__ import annotations

from pathlib import Path

from shelfsense_common.config import get_settings
from shelfsense_common.logging import get_logger
from shelfsense_common.pos_loader import load_transactions

from shelfsense_api.db import get_session
from shelfsense_api.repository import upsert_transactions

log = get_logger("api")


def resolve_pos_csv(configured: str) -> Path | None:
    """Find the POS CSV.

    The real file carries a download suffix (``Brigade_Bangalore_10_April_26 (1)bc6219c.csv``), so
    if the configured path is absent we fall back to a ``*.csv`` in its directory (preferring a
    Brigade file) rather than trusting the exact name.
    """
    path = Path(configured)
    if path.is_file():
        return path

    search_dir = path.parent if path.suffix else path
    if not search_dir.is_dir():
        return None
    candidates = sorted(search_dir.glob("*.csv"))
    brigade = [c for c in candidates if c.name.lower().startswith("brigade")]
    chosen = brigade or candidates
    return chosen[0] if chosen else None


def load_pos_into_db() -> int:
    """Load the POS CSV into Postgres (idempotent). Returns rows upserted (0 if none)."""
    settings = get_settings()
    csv_path = resolve_pos_csv(settings.pos_csv_path)
    if csv_path is None:
        log.warning("pos_csv_not_found", configured=settings.pos_csv_path)
        return 0
    try:
        txns = load_transactions(csv_path, store_tz=settings.store_timezone)
        with get_session() as session:
            count = upsert_transactions(session, txns)
        log.info("pos_loaded", path=str(csv_path), transactions=count)
        return count
    except Exception as exc:  # never block API startup on POS data
        log.warning("pos_load_failed", path=str(csv_path), error=str(exc))
        return 0
