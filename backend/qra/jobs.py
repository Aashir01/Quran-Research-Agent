"""Background jobs (WP-03).

A full 1,651-root sweep or a deep research run is a job, not a request. Two
backends behind one interface:

* **Arq (Redis)** — the default the moment ``QRA_REDIS_URL`` points at a live
  Redis. Survives process restarts, runs on separate workers.
* **Thread executor** — the documented fallback. Fine for a laptop or CI, and
  honest about what it is: jobs die with the process.

Whichever runs, the contract is identical — enqueue returns a handle, the job
reports progress, and it can be cancelled. Progress is a first-class field
because a sweep that takes four minutes with no output is indistinguishable
from a hang.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from qra.config import settings
from qra.db import session_scope

_JOBS: dict[str, dict[str, Any]] = {}
_CANCELLED: set[str] = set()
_LOCK = threading.Lock()


@dataclass
class Progress:
    """What a long job reports while it runs."""

    done: int = 0
    total: int = 0
    stage: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def fraction(self) -> float:
        return round(self.done / self.total, 4) if self.total else 0.0

    def to_dict(self) -> dict:
        return {**asdict(self), "fraction": self.fraction}


class JobCancelled(RuntimeError):
    """Raised inside a job when the caller cancelled it."""


class JobHandle:
    """Passed into the job body so it can report progress and notice cancellation."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.progress = Progress()

    def report(self, done: int, total: int, stage: str = "", **detail: Any) -> None:
        self.progress = Progress(done=done, total=total, stage=stage, detail=detail)
        with _LOCK:
            if self.job_id in _JOBS:
                _JOBS[self.job_id]["progress"] = self.progress.to_dict()

    def checkpoint(self) -> None:
        """Call inside loops. Raises if the job was cancelled."""
        with _LOCK:
            cancelled = self.job_id in _CANCELLED
        if cancelled:
            raise JobCancelled(f"job {self.job_id} cancelled")


def redis_available() -> bool:
    try:
        import redis  # noqa: PLC0415

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5)
        client.ping()
        return True
    except Exception:  # noqa: BLE001 - absence of Redis is an expected state
        return False


def backend() -> str:
    return "arq" if redis_available() else "thread"


def enqueue(name: str, fn: Callable[..., dict], *, meta: dict | None = None) -> dict:
    """Run ``fn(session)`` — or ``fn(session, handle)`` — in the background."""
    job_id = f"{name}-{uuid.uuid4().hex[:12]}"
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "name": name,
            "status": "queued",
            "queued_at": datetime.now(UTC).isoformat(),
            "backend": backend(),
            "progress": Progress().to_dict(),
            "meta": meta or {},
        }

    handle = JobHandle(job_id)

    def target() -> None:
        with _LOCK:
            _JOBS[job_id]["status"] = "running"
            _JOBS[job_id]["started_at"] = datetime.now(UTC).isoformat()
        try:
            with session_scope() as session:
                # Jobs that want progress take a handle; simple ones do not.
                import inspect

                takes_handle = len(inspect.signature(fn).parameters) > 1
                result = fn(session, handle) if takes_handle else fn(session)
            with _LOCK:
                _JOBS[job_id].update(
                    status="complete",
                    result=result,
                    finished_at=datetime.now(UTC).isoformat(),
                )
        except JobCancelled:
            with _LOCK:
                _JOBS[job_id].update(
                    status="cancelled",
                    finished_at=datetime.now(UTC).isoformat(),
                    progress=handle.progress.to_dict(),
                )
        except Exception as exc:  # noqa: BLE001 - surfaced through the job record
            with _LOCK:
                _JOBS[job_id].update(
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    traceback=traceback.format_exc()[-2000:],
                    finished_at=datetime.now(UTC).isoformat(),
                )
        finally:
            with _LOCK:
                _CANCELLED.discard(job_id)

    threading.Thread(target=target, daemon=True, name=job_id).start()
    with _LOCK:
        return dict(_JOBS[job_id])


def cancel(job_id: str) -> dict | None:
    """Ask a job to stop. It stops at its next checkpoint, not instantly."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        if job["status"] in ("complete", "failed", "cancelled"):
            return dict(job)
        _CANCELLED.add(job_id)
        job["status"] = "cancelling"
        return dict(job)


def job_status(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(limit: int = 50) -> list[dict]:
    with _LOCK:
        return [dict(j) for j in list(_JOBS.values())[-limit:]]


# --- Arq worker settings (production path) ---------------------------------


async def run_research_job(ctx, question: str, language: str, run_id: str) -> dict:  # pragma: no cover
    from qra.agents.graph import run_research

    with session_scope() as session:
        return run_research(session, question, language=language, run_id=run_id)


async def run_sweep_job(ctx, kind: str, params: dict) -> dict:  # pragma: no cover
    from qra.analytics import distribution

    with session_scope() as session:
        if kind == "makki_madani":
            return distribution.makki_madani_sweep(session, **params)
        raise ValueError(f"unknown sweep {kind}")


class WorkerSettings:  # pragma: no cover - used by `arq qra.jobs.WorkerSettings`
    """Run with: ``arq qra.jobs.WorkerSettings``."""

    functions = [run_research_job, run_sweep_job]
    max_jobs = 4
    job_timeout = 3600
    keep_result = 3600

    @staticmethod
    def redis_settings():
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(settings.redis_url)
