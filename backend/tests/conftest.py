"""Test fixtures.

Tests that need the corpus skip cleanly when no ingested database is reachable,
so the pure-logic suite (normalisation, statistics, the scripture guard) runs
anywhere — including CI without Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select


@pytest.fixture(scope="session")
def corpus_available() -> bool:
    try:
        from qra.db import SessionLocal
        from qra.models import Ayah

        with SessionLocal() as session:
            return (session.scalar(select(func.count()).select_from(Ayah)) or 0) == 6236
    except Exception:  # noqa: BLE001 - absence of a database is a skip, not a failure
        return False


@pytest.fixture
def session(corpus_available):
    if not corpus_available:
        pytest.skip("no ingested corpus reachable — run `qra ingest` first")
    from qra.db import SessionLocal

    with SessionLocal() as session:
        yield session
