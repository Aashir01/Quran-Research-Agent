"""Engine, session factory and schema bootstrap."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from qra.config import settings
from qra.models import Base

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def has_pgvector(conn) -> bool:
    row = conn.execute(
        text("select 1 from pg_available_extensions where name = 'vector'")
    ).first()
    return row is not None


def init_db() -> dict[str, bool]:
    """Create the schema. Idempotent.

    pgvector is used when available and silently skipped when not: with 6,236
    ayat, brute-force cosine in numpy is fast enough that requiring the
    extension would be gatekeeping, not engineering.
    """
    info = {"pgvector": False, "pg_trgm": False}
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            if has_pgvector(conn):
                conn.execute(text("create extension if not exists vector"))
                info["pgvector"] = True
            try:
                conn.execute(text("create extension if not exists pg_trgm"))
                info["pg_trgm"] = True
            except Exception:  # noqa: BLE001 - optional accelerator only
                pass
        Base.metadata.create_all(conn)
    return info


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
