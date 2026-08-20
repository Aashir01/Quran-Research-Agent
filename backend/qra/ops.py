"""Operations: structured logging, correlation ids, rate limiting (WP-60).

Every request gets a correlation id, which flows into the log line, the trace
span and the response header. When a researcher says "the run I started at
2pm returned something odd", that id is how you find it — and it is why the
logs are JSON rather than prose.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar

from qra.config import settings

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
principal_id: ContextVar[str] = ContextVar("principal_id", default="-")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the correlation id always present."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id.get(),
            "principal": principal_id.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Third-party loggers are chatty at INFO and drown the request lines that
    # actually carry correlation ids.
    for noisy in ("alembic", "httpx", "httpcore", "urllib3", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log(name: str, message: str, **fields) -> None:
    logger = logging.getLogger(name)
    record = logger.makeRecord(name, logging.INFO, __file__, 0, message, (), None)
    record.extra_fields = fields
    logger.handle(record)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class SlidingWindowLimiter:
    """Per-principal request limiter.

    In-process, which is the honest scope: it protects one API worker from one
    runaway client. Multi-worker deployments should put a shared limiter in
    front — noted here rather than pretended away.
    """

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int]:
        if self.per_minute <= 0:
            return True, 0
        now = time.time()
        window = self._events[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            retry_after = int(61 - (now - window[0]))
            return False, max(retry_after, 1)
        window.append(now)
        return True, 0


_limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)


def install(app) -> None:
    """Attach correlation ids, structured request logs and rate limiting."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def _observability(request: Request, call_next):
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex[:16]
        correlation_id.set(cid)

        from qra.security.auth import current_principal

        principal = current_principal(request)
        principal_id.set(str(principal.user_id) if principal else "anon")

        # Rate limit per principal, falling back to client host for anonymous
        # callers so one unauthenticated IP cannot exhaust the process.
        key = principal_id.get()
        if key == "anon":
            key = f"ip:{request.client.host if request.client else 'unknown'}"
        allowed, retry_after = _limiter.check(key)
        if not allowed:
            return JSONResponse(
                {"detail": "rate limit exceeded", "retry_after_seconds": retry_after},
                status_code=429,
                headers={"retry-after": str(retry_after), "x-correlation-id": cid},
            )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log(
                "qra.request",
                "request failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        duration = round((time.perf_counter() - started) * 1000, 2)
        response.headers["x-correlation-id"] = cid
        log(
            "qra.request",
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration,
        )
        return response


def readiness(session) -> dict:
    """Is this instance ready to serve — not merely alive?

    Liveness says the process is up. Readiness says the corpus is loaded, the
    migrations are current and the derived indexes exist; a instance that is up
    with an empty database should not receive traffic.
    """
    from sqlalchemy import func, select

    from qra.models import Ayah, SearchPosting, Segment

    checks = {}
    try:
        ayat = session.scalar(select(func.count()).select_from(Ayah)) or 0
        checks["corpus"] = {"ok": ayat == 6236, "ayat": ayat, "expected": 6236}
    except Exception as exc:  # noqa: BLE001
        checks["corpus"] = {"ok": False, "error": str(exc)[:200]}
    try:
        segments = session.scalar(select(func.count()).select_from(Segment)) or 0
        checks["morphology"] = {"ok": segments > 120_000, "segments": segments}
    except Exception as exc:  # noqa: BLE001
        checks["morphology"] = {"ok": False, "error": str(exc)[:200]}
    try:
        postings = session.scalar(select(func.count()).select_from(SearchPosting)) or 0
        checks["lexical_index"] = {"ok": postings > 0, "postings": postings}
    except Exception as exc:  # noqa: BLE001
        checks["lexical_index"] = {"ok": False, "error": str(exc)[:200]}
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text as sql_text

        current = session.execute(sql_text("select version_num from alembic_version")).scalar()
        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        checks["migrations"] = {"ok": current == head, "current": current, "head": head}
    except Exception as exc:  # noqa: BLE001 - alembic is optional at runtime
        checks["migrations"] = {"ok": None, "note": f"not determinable: {str(exc)[:120]}"}

    ready = all(c.get("ok") is not False for c in checks.values())
    return {"ready": ready, "checks": checks}
