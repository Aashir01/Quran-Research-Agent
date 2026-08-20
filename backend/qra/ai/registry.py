"""Model registry (WP-09).

Model ids are configuration, never code. ``config/models.yaml`` is the single
place a model name appears, and every entry carries ``verified_on`` — the date
someone confirmed the id was live — because provider model names change far
faster than this codebase will.

A stale ``verified_on`` is a prompt to check, not a failure: the registry
reports the age and carries on. Failing closed on a date would take a working
system down for a bookkeeping lapse.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from qra.config import REPO_ROOT, settings

# ``QRA_MODELS_CONFIG`` (via Settings.models_config) points this elsewhere — an
# institution running its own approved-model list should not have to fork the repo.
REGISTRY_PATH = Path(settings.models_config or REPO_ROOT / "config" / "models.yaml")
# Beyond this, the registry warns that an id may have moved.
STALE_AFTER_DAYS = 180


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    kind: str  # chat | embedding | rerank | transcription
    id: str
    api: str
    tier: str = "balanced"
    base_url: str | None = None
    env_key: str | None = None
    local: bool = False
    context: int | None = None
    dim: int | None = None
    structured_output: str = "none"  # native | json_mode | none
    multilingual: bool = False
    languages: tuple[str, ...] = ()
    price_in: float = 0.0
    price_out: float = 0.0
    verified_on: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def age_days(self) -> int | None:
        if not self.verified_on:
            return None
        try:
            return (date.today() - datetime.fromisoformat(str(self.verified_on)).date()).days
        except ValueError:
            return None

    @property
    def stale(self) -> bool:
        age = self.age_days
        return age is not None and age > STALE_AFTER_DAYS

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.price_in + output_tokens * self.price_out) / 1_000_000

    def key_from_env(self) -> str | None:
        return os.environ.get(self.env_key) if self.env_key else None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "kind": self.kind,
            "id": self.id,
            "api": self.api,
            "tier": self.tier,
            "local": self.local,
            "context": self.context,
            "structured_output": self.structured_output,
            "verified_on": self.verified_on,
            "age_days": self.age_days,
            "stale": self.stale,
        }


class RegistryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _raw() -> dict:
    if not REGISTRY_PATH.exists():
        raise RegistryError(
            f"model registry not found at {REGISTRY_PATH}. Set QRA_MODELS_CONFIG or restore "
            "config/models.yaml — model ids deliberately do not live in code."
        )
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def reload() -> None:
    _raw.cache_clear()


def specs(kind: str = "chat") -> list[ModelSpec]:
    out: list[ModelSpec] = []
    for provider, block in (_raw().get(kind) or {}).items():
        for model in block.get("models", []):
            out.append(
                ModelSpec(
                    provider=provider,
                    kind=kind,
                    id=model["id"],
                    api=block.get("api", provider),
                    tier=model.get("tier", "balanced"),
                    base_url=block.get("base_url"),
                    env_key=block.get("env_key"),
                    local=bool(block.get("local")),
                    context=model.get("context"),
                    dim=model.get("dim"),
                    structured_output=model.get("structured_output", "none"),
                    multilingual=bool(model.get("multilingual")),
                    languages=tuple(model.get("languages", ())),
                    price_in=float(model.get("price_in", 0.0)),
                    price_out=float(model.get("price_out", 0.0)),
                    verified_on=model.get("verified_on"),
                    extra={k: v for k, v in block.items() if k not in ("models",)},
                )
            )
    return out


def find(kind: str, provider: str, model_id: str | None = None) -> ModelSpec | None:
    for spec in specs(kind):
        if spec.provider == provider and (model_id is None or spec.id == model_id):
            return spec
    return None


def providers(kind: str = "chat") -> list[str]:
    return sorted({s.provider for s in specs(kind)})


def routing_policy() -> dict:
    return (_raw().get("routing") or {}).get("default_policy", {})


def fallback_chains() -> dict[str, list[str]]:
    return (_raw().get("routing") or {}).get("fallback_chains", {})


def audit() -> dict:
    """What is registered, how old each entry is, and which have credentials."""
    rows = []
    for kind in ("chat", "embedding", "rerank", "transcription"):
        for spec in specs(kind):
            rows.append({**spec.to_dict(), "has_credential": bool(spec.local or spec.key_from_env())})
    stale = [r for r in rows if r["stale"]]
    return {
        "registry_path": str(REGISTRY_PATH),
        "models": len(rows),
        "by_kind": {
            kind: len([r for r in rows if r["kind"] == kind])
            for kind in ("chat", "embedding", "rerank", "transcription")
        },
        "configured": [r for r in rows if r["has_credential"]],
        "stale": stale,
        "note": (
            f"{len(stale)} entries are older than {STALE_AFTER_DAYS} days. That is a prompt to "
            "re-check the id with the provider, not an error — failing closed on a date would "
            "take a working system down for a bookkeeping lapse."
        ),
        "entries": rows,
    }
