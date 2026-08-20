"""Liveness probes for local providers.

A hosted provider announces itself with a credential: if the key is set, it is
reasonable to try. A local one announces itself with nothing at all — Ollama is
in the config whether or not anything is listening on 11434, and a
sentence-transformers entry is real only if the wheel is installed.

So ``/status`` would otherwise report "a model is available" on a laptop with no
Ollama running, which is exactly the sort of small lie that makes a system
untrustworthy. These probes are cheap, cached for a minute, and never raise:
they answer one question, "would a call to this have any chance", and routing
itself still relies on the fallback chain rather than on the probe.
"""

from __future__ import annotations

import time
from importlib.util import find_spec

import httpx

from qra.ai.registry import ModelSpec

TTL_SECONDS = 60.0
_CACHE: dict[str, tuple[float, bool]] = {}

# api -> the module that must be importable for a local adapter to work.
_IMPORT_REQUIRED = {
    "sentence_transformers": "sentence_transformers",
    "whisper": "whisper",
    "faster_whisper": "faster_whisper",
}


def _cached(key: str, compute) -> bool:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < TTL_SECONDS:
        return hit[1]
    value = compute()
    _CACHE[key] = (now, value)
    return value


def _http_ok(url: str) -> bool:
    try:
        with httpx.Client(timeout=1.5) as client:
            return client.get(url).status_code < 500
    except Exception:  # noqa: BLE001 - "not running" is the expected answer here
        return False


def reachable(spec: ModelSpec) -> bool:
    """Is this provider plausibly usable right now?

    Hosted providers are judged by credential alone — probing them would cost
    money and rate limit, and the fallback chain handles the rest.
    """
    if not spec.local:
        return bool(spec.key_from_env())

    module = _IMPORT_REQUIRED.get(spec.api)
    if module:
        return _cached(f"import:{module}", lambda: find_spec(module) is not None)

    base = (spec.base_url or "").rstrip("/")
    if not base:
        return True
    if spec.api == "ollama":
        return _cached(f"http:{base}/api/tags", lambda: _http_ok(f"{base}/api/tags"))
    return _cached(f"http:{base}/models", lambda: _http_ok(f"{base}/models"))


def clear() -> None:
    _CACHE.clear()
