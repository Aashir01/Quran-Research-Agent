"""Adapter registry (WP-09).

Adding a provider is exactly two edits: one block in ``config/models.yaml`` and,
only if it speaks a wire protocol nobody else speaks, one class here. No agent,
tool or router code changes — which is the whole acceptance criterion.
"""

from __future__ import annotations

from qra.ai.adapters.chat import CHAT_ADAPTERS
from qra.ai.adapters.embed import EMBEDDING_ADAPTERS
from qra.ai.adapters.rerank import RERANK_ADAPTERS
from qra.ai.adapters.transcribe import TRANSCRIPTION_ADAPTERS
from qra.ai.base import ProviderUnavailable
from qra.ai.registry import ModelSpec

BY_KIND: dict[str, dict[str, type]] = {
    "chat": CHAT_ADAPTERS,
    "embedding": EMBEDDING_ADAPTERS,
    "rerank": RERANK_ADAPTERS,
    "transcription": TRANSCRIPTION_ADAPTERS,
}


def build(spec: ModelSpec, *, api_key: str | None = None, base_url: str | None = None):
    """Instantiate the adapter for a registry entry."""
    table = BY_KIND.get(spec.kind)
    if table is None:
        raise ProviderUnavailable(
            f"unknown model kind {spec.kind!r}", reason="policy", provider=spec.provider
        )
    adapter = table.get(spec.api)
    if adapter is None:
        raise ProviderUnavailable(
            f"no {spec.kind} adapter speaks {spec.api!r} "
            f"(have: {', '.join(sorted(table))})",
            reason="policy",
            provider=spec.provider,
        )
    return adapter(spec, api_key=api_key, base_url=base_url)


def supported(kind: str) -> list[str]:
    return sorted(BY_KIND.get(kind, {}))


def coverage() -> dict:
    """Which registry entries actually have an adapter behind them.

    Run in CI: a config block with no adapter is a model that will fail at the
    worst possible moment, midway through a research run.
    """
    from qra.ai import registry

    missing, ok = [], 0
    for kind in BY_KIND:
        for spec in registry.specs(kind):
            if spec.api in BY_KIND[kind]:
                ok += 1
            else:
                missing.append({"kind": kind, "provider": spec.provider, "api": spec.api})
    return {"covered": ok, "missing": missing, "adapters": {k: supported(k) for k in BY_KIND}}


__all__ = ["BY_KIND", "build", "coverage", "supported"]
