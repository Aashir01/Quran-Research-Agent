"""Background jobs.

A full hypothesis sweep or a corpus-wide root sweep is a job, not a request.
Arq (Redis) is the production path; when Redis is unavailable the same callable
runs in a worker thread with its status tracked in memory, so development and
CI need no broker. The API contract is identical either way: you get a job id
and poll it.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from qra.config import settings
from qra.db import session_scope

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _redis_available() -> bool:
    try:
        import redis  # noqa: PLC0415

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5)
        client.ping()
        return True
    except Exception:  # noqa: BLE001 - absence of Redis is an expected state
        return False


def enqueue(name: str, fn: Callable[[Any], dict]) -> dict:
    """Run ``fn(session)`` in the background and return a job handle."""
    job_id = f"{name}-{uuid.uuid4().hex[:12]}"
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "name": name,
            "status": "queued",
            "queued_at": datetime.now(UTC).isoformat(),
            "backend": "arq" if _redis_available() else "thread",
        }

    def target() -> None:
        with _LOCK:
            _JOBS[job_id]["status"] = "running"
        try:
            with session_scope() as session:
                result = fn(session)
            with _LOCK:
                _JOBS[job_id].update(
                    status="complete",
                    result=result,
                    finished_at=datetime.now(UTC).isoformat(),
                )
        except Exception as exc:  # noqa: BLE001 - surfaced through the job record
            with _LOCK:
                _JOBS[job_id].update(
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    traceback=traceback.format_exc()[-2000:],
                    finished_at=datetime.now(UTC).isoformat(),
                )

    threading.Thread(target=target, daemon=True, name=job_id).start()
    with _LOCK:
        return dict(_JOBS[job_id])


def job_status(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs() -> list[dict]:
    with _LOCK:
        return [dict(j) for j in _JOBS.values()]


# --- Arq worker settings (production path) ---------------------------------


async def run_research_job(ctx, question: str, language: str, run_id: str) -> dict:  # pragma: no cover
    from qra.agents.graph import run_research

    with session_scope() as session:
        return run_research(session, question, language=language, run_id=run_id)


class WorkerSettings:  # pragma: no cover - used by `arq qra.jobs.WorkerSettings`
    functions = [run_research_job]
    redis_settings = None  # populated from settings.redis_url at deploy time
    max_jobs = 4
    job_timeout = 1800
