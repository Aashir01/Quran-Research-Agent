"""Content-addressed cache (WP-06).

Cached: model calls (keyed on provider + model + prompt + tool set), embeddings,
and expensive analytics sweeps.

Not cached: deterministic retrieval. A root lookup is an indexed SQL query that
returns in single-digit milliseconds; a cache lookup plus deserialisation would
cost more than the thing it replaces, and it would add a way for the corpus and
the answer to disagree. That asymmetry is the whole reason this module states
what it will not do.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from qra.config import settings
from qra.models import CacheEntry

# Cacheable kinds. Anything not listed here is a deliberate omission.
KINDS = ("model_call", "embedding", "analytics", "rerank")

_STATS = {"hits": 0, "misses": 0, "writes": 0}


def key_for(kind: str, payload: dict) -> str:
    """Stable hash of the request. Ordering and whitespace must not matter."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{kind}|{canonical}".encode()).hexdigest()


def get(session: Session, kind: str, payload: dict) -> Any | None:
    if not settings.cache_enabled:
        return None
    entry = session.get(CacheEntry, key_for(kind, payload))
    if entry is None:
        _STATS["misses"] += 1
        return None
    if datetime.now(UTC) - entry.created_at.replace(tzinfo=UTC) > timedelta(
        seconds=settings.cache_ttl_seconds
    ):
        session.delete(entry)
        session.commit()
        _STATS["misses"] += 1
        return None
    entry.hits += 1
    entry.last_used_at = datetime.now(UTC)
    session.commit()
    _STATS["hits"] += 1
    return entry.value.get("v")


def put(session: Session, kind: str, payload: dict, value: Any) -> None:
    if not settings.cache_enabled or kind not in KINDS:
        return
    key = key_for(kind, payload)
    entry = session.get(CacheEntry, key)
    if entry is None:
        entry = CacheEntry(key=key, kind=kind, value={"v": value})
        session.add(entry)
    else:
        entry.value = {"v": value}
        entry.last_used_at = datetime.now(UTC)
    session.commit()
    _STATS["writes"] += 1


def stats(session: Session | None = None) -> dict:
    total = _STATS["hits"] + _STATS["misses"]
    payload = {
        **_STATS,
        "hit_rate": round(_STATS["hits"] / total, 4) if total else 0.0,
        "enabled": settings.cache_enabled,
        "ttl_seconds": settings.cache_ttl_seconds,
        "not_cached": (
            "deterministic retrieval — the SQL is cheaper than the cache lookup, and a "
            "cache is one more way for the corpus and the answer to disagree"
        ),
    }
    if session is not None:
        rows = session.execute(
            select(CacheEntry.kind, func.count(), func.sum(CacheEntry.hits)).group_by(
                CacheEntry.kind
            )
        ).all()
        payload["stored"] = {k: {"entries": n, "hits": int(h or 0)} for k, n, h in rows}
    return payload


def clear(session: Session, kind: str | None = None) -> int:
    stmt = delete(CacheEntry)
    if kind:
        stmt = stmt.where(CacheEntry.kind == kind)
    removed = session.execute(stmt).rowcount
    session.commit()
    return removed
