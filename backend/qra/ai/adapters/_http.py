"""Shared HTTP plumbing for provider adapters.

One job: turn every possible failure into a :class:`ProviderUnavailable` with a
truthful ``reason``. The router's fallback logic is only as good as this
classification — a rate limit that looks like a timeout gets retried wrongly,
and a refusal that looks like an outage gets hidden from the user.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from qra.ai.base import ProviderUnavailable

DEFAULT_TIMEOUT = 180.0
LOCAL_TIMEOUT = 600.0  # a 70B model on a laptop is slow, not broken


def reason_for_status(status: int) -> str:
    if status in (401, 403):
        return "no_credential"
    if status == 429:
        return "rate_limit"
    if status in (408, 504):
        return "timeout"
    if status == 451:
        return "policy"
    if 500 <= status < 600:
        return "unavailable"
    return "unavailable"


def _excerpt(response: httpx.Response, limit: int = 400) -> str:
    try:
        return json.dumps(response.json())[:limit]
    except Exception:  # noqa: BLE001 - error bodies are not always JSON
        return response.text[:limit]


def post(
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    data: Any = None,
    files: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    params: dict | None = None,
) -> dict:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url, headers=headers, json=json_body, data=data, files=files, params=params
            )
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable(f"{provider} timed out", reason="timeout", provider=provider) from exc
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(
            f"{provider} unreachable: {exc}", reason="unavailable", provider=provider
        ) from exc
    if response.status_code >= 400:
        raise ProviderUnavailable(
            f"{provider} returned {response.status_code}: {_excerpt(response)}",
            reason=reason_for_status(response.status_code),
            provider=provider,
        )
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailable(
            f"{provider} returned non-JSON: {response.text[:200]}",
            reason="unavailable",
            provider=provider,
        ) from exc


def require_key(spec, api_key: str | None) -> str:
    """Local providers need no key; hosted ones fail fast and say which env var."""
    key = api_key or spec.key_from_env()
    if not key and not spec.local:
        raise ProviderUnavailable(
            f"no credential for {spec.provider} (set {spec.env_key or 'its API key'}, "
            "or store one per-user via /auth/keys)",
            reason="no_credential",
            provider=spec.provider,
        )
    return key or ""


def json_from_text(raw: str) -> Any:
    """Last-resort extraction for models with no structured-output support."""
    import re

    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    candidate = fenced.group(1) if fenced else raw
    match = re.search(r"[\{\[].*[\}\]]", candidate, re.S)
    if not match:
        raise ValueError(f"no JSON in model output: {raw[:200]}")
    return json.loads(match.group(0))
