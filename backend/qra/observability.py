"""Tracing.

LangFuse when it is configured and installed; a no-op recorder otherwise. The
no-op is not a stub — it still keeps the last runs in memory and serves them at
``/meta/traces``, because "which tools did that agent actually call, in what
order, and how long did each take" is the question you need answered at 2am,
and it should not require a SaaS account.

Spans record *what was asked and what came back in outline*: tool name,
arguments, row counts, durations. Retrieved scripture is not shipped to a third
party — an ayah id is enough to reconstruct any span locally, and sending the
corpus text to an observability vendor would be both pointless and a licence
question nobody needs.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

from qra.config import settings


@dataclass
class Span:
    name: str
    kind: str  # agent | tool | llm | job
    run_id: str
    started_at: float
    duration_ms: float | None = None
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Recorder:
    """In-process trace buffer. Always on; costs nothing."""

    def __init__(self, capacity: int = 200):
        self._spans: deque[Span] = deque(maxlen=capacity * 20)
        self._runs: deque[str] = deque(maxlen=capacity)

    def record(self, span: Span) -> None:
        self._spans.append(span)
        if span.run_id not in self._runs:
            self._runs.append(span.run_id)

    def runs(self) -> list[dict]:
        out = []
        for run_id in reversed(self._runs):
            spans = [s for s in self._spans if s.run_id == run_id]
            if not spans:
                continue
            out.append(
                {
                    "run_id": run_id,
                    "spans": len(spans),
                    "started_at": min(s.started_at for s in spans),
                    "duration_ms": round(sum(s.duration_ms or 0 for s in spans), 1),
                    "errors": sum(1 for s in spans if s.error),
                    "tools": sorted({s.name for s in spans if s.kind == "tool"}),
                }
            )
        return out

    def spans(self, run_id: str) -> list[dict]:
        return [s.to_dict() for s in self._spans if s.run_id == run_id]


RECORDER = Recorder()


class _LangfuseClient:
    """Thin adapter. Import failure or a missing key degrades to local-only."""

    def __init__(self):
        self._client = None
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            return
        try:
            from langfuse import Langfuse  # noqa: PLC0415

            self._client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception:  # noqa: BLE001 - observability must never break a run
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def send(self, span: Span) -> None:
        if self._client is None:
            return
        try:
            self._client.trace(id=span.run_id, name="qra.research").span(
                name=span.name,
                start_time=span.started_at,
                metadata={"kind": span.kind, "duration_ms": span.duration_ms},
                input=span.input,
                output=span.output,
                level="ERROR" if span.error else "DEFAULT",
                status_message=span.error,
            )
        except Exception:  # noqa: BLE001 - never let a trace failure fail the work
            pass


_LANGFUSE = _LangfuseClient()


def _summarise(value: Any, *, depth: int = 0) -> Any:
    """Shrink a payload to shape and size — never ship corpus text off-box."""
    if depth > 2:
        return "…"
    if isinstance(value, dict):
        keys = ("total_occurrences", "total_ayat", "verdict", "coverage", "root", "query", "ref")
        summary = {k: value[k] for k in keys if k in value}
        for key in ("hits", "results", "violating", "supporting", "entries", "matches"):
            if isinstance(value.get(key), list):
                summary[f"{key}_count"] = len(value[key])
        return summary or {k: _summarise(v, depth=depth + 1) for k, v in list(value.items())[:6]}
    if isinstance(value, list):
        return {"count": len(value)}
    if isinstance(value, str):
        return value[:120]
    return value


@contextmanager
def trace(name: str, *, kind: str = "tool", run_id: str | None = None, **inputs):
    """Time a unit of work and record it. Never raises on its own account."""
    span = Span(
        name=name,
        kind=kind,
        run_id=run_id or uuid.uuid4().hex[:16],
        started_at=time.time(),
        input={k: _summarise(v) for k, v in inputs.items()},
    )
    started = time.perf_counter()
    result_holder: dict[str, Any] = {}
    try:
        yield result_holder
    except Exception as exc:
        span.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        span.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if "result" in result_holder:
            span.output = _summarise(result_holder["result"])
        RECORDER.record(span)
        _LANGFUSE.send(span)


def status() -> dict:
    return {
        "langfuse": {
            "enabled": _LANGFUSE.enabled,
            "host": settings.langfuse_host if _LANGFUSE.enabled else None,
            "reason": None
            if _LANGFUSE.enabled
            else "QRA_LANGFUSE_PUBLIC_KEY / QRA_LANGFUSE_SECRET_KEY not set, or the SDK is not installed",
        },
        "local_recorder": {"enabled": True, "runs_buffered": len(RECORDER.runs())},
        "note": (
            "Spans carry tool names, argument shapes, row counts and durations. Corpus text is "
            "never sent to a third party — an ayah id reconstructs any span locally."
        ),
    }
