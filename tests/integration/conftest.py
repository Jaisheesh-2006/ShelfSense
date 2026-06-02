"""Integration-test fixtures: a TestClient backed by a throwaway SQLite database.

Hermetic — no Postgres/POS file required. We rebind the API's engine to a per-test SQLite file
(`configure_engine`) and point POS at an empty directory so the startup load is a graceful no-op.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator:
    monkeypatch.setenv("POS_CSV_PATH", str(tmp_path / "no_pos"))

    from shelfsense_common.config import get_settings

    get_settings.cache_clear()

    from shelfsense_api import db

    db.configure_engine(f"sqlite+pysqlite:///{(tmp_path / 'test.db').as_posix()}")

    from fastapi.testclient import TestClient
    from shelfsense_api.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
