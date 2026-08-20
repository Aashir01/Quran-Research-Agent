"""Role-based routing and fallback (WP-10, WP-11, WP-12, WP-13).

Three ideas, in the order they matter.

**Roles, not call sites.** An agent asks for ``planner`` or ``hadith``; it never
names a model. Which model serves a role is policy in ``config/models.yaml``, so
swapping the Critic onto a different provider is a config edit, not a diff
across the agent graph.

**Fallback ends in nothing, deliberately.** Every chain terminates in
``deterministic``. When it gets there the router raises
:class:`NoModelAvailable` and the caller takes its deterministic path — the run
still retrieves, counts, tests hypotheses and verifies citations, and the draft
comes back marked ``undrafted``. A weaker model is *not* the last resort,
because a silently-degraded Critic that approves a bad claim is worse than a
Critic that is visibly absent.

**Every attempt is recorded.** :attr:`Router.attempts` is the audit trail that
says which provider served which role, what each failure was, and what the run
cost. Without it "the answer changed" is unanswerable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from qra.ai import registry
from qra.ai.adapters import build
from qra.ai.base import (
    ChatResult,
    EmbeddingResult,
    ProviderUnavailable,
    RerankResult,
    TranscriptionResult,
    estimate_tokens,
)
from qra.ai.registry import ModelSpec
from qra.budget import BudgetExceeded, RunBudget

TERMINAL = "deterministic"

# Hard requirements filter candidates out. A model that cannot return
# structured output cannot serve a role that parses structured output.
_HARD_NEEDS: dict[str, Callable[[ModelSpec], bool]] = {
    "long_context": lambda s: (s.context or 0) >= 100_000,
    "structured_output": lambda s: s.structured_output != "none",
}
# Soft preferences only reorder. `arabic` is soft because no chat provider
# self-declares Arabic competence honestly enough to filter on it; the tier
# ordering plus the golden eval is what actually decides this.
_SOFT_NEEDS = ("arabic",)

# When a role's tier has no chain of its own, borrow the neighbouring one.
_TIER_NEIGHBOURS = {"reasoning": ["balanced", "fast"], "balanced": ["reasoning", "fast"],
                    "fast": ["balanced", "reasoning"]}


class NoModelAvailable(RuntimeError):
    """Every provider in the chain failed, or none was configured.

    Not an error condition for the system as a whole — it is the documented
    state that turns agents deterministic. Carries the attempt log so the run
    can report *why* there was no model rather than just that there wasn't.
    """

    def __init__(self, role: str, attempts: list[dict]):
        reasons = ", ".join(f"{a['provider']}: {a['reason']}" for a in attempts) or "none configured"
        super().__init__(
            f"no model available for role {role!r} ({reasons}). "
            "Falling back to deterministic behaviour: retrieval, counts, hypothesis "
            "verdicts and citation verification are unaffected; prose is not drafted."
        )
        self.role = role
        self.attempts = attempts


@dataclass
class Attempt:
    role: str
    provider: str
    model: str
    ok: bool
    ms: float
    reason: str = ""
    detail: str = ""
    cached: bool = False
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


TIERS = ("reasoning", "balanced", "fast")


def _tier_of(role: str) -> str:
    """A role's tier from policy. Bare tier names are accepted too, so older
    call sites that asked for "reasoning" keep working unchanged."""
    policy = registry.routing_policy().get(role)
    if policy:
        return policy.get("tier", "balanced")
    return role if role in TIERS else "balanced"


def _needs_of(role: str) -> list[str]:
    return list((registry.routing_policy().get(role) or {}).get("needs", []))


def _chain_for(tier: str) -> list[str]:
    chains = registry.fallback_chains()
    if tier in chains:
        return list(chains[tier])
    for neighbour in _TIER_NEIGHBOURS.get(tier, []):
        if neighbour in chains:
            return list(chains[neighbour])
    return [TERMINAL]


def _score(spec: ModelSpec, tier: str, soft: list[str]) -> tuple:
    """Lower is better. Exact tier first, then soft preferences, then price."""
    exact = 0 if spec.tier == tier else 1
    multilingual = 0 if ("arabic" in soft and spec.multilingual) else 1
    return (exact, multilingual, spec.price_in + spec.price_out)


def candidates(
    role: str,
    *,
    kind: str = "chat",
    avoid_providers: tuple[str, ...] = (),
    require_credential: bool = True,
    key_resolver: Callable[[str], str | None] | None = None,
    probe_local: bool = False,
) -> list[ModelSpec]:
    """The ordered list the router will actually try, credentials included.

    ``probe_local`` adds a liveness check for local providers. It is off during
    routing — the fallback chain already handles a dead Ollama, and a probe on
    every call would just be a slower way to discover the same thing — and on
    for ``/status``, which is asked to state the truth rather than to try.
    """
    tier = _tier_of(role)
    needs = _needs_of(role)
    hard = [_HARD_NEEDS[n] for n in needs if n in _HARD_NEEDS]
    soft = [n for n in needs if n in _SOFT_NEEDS]
    by_provider: dict[str, list[ModelSpec]] = {}
    for spec in registry.specs(kind):
        by_provider.setdefault(spec.provider, []).append(spec)

    out: list[ModelSpec] = []
    for provider in _chain_for(tier):
        if provider == TERMINAL:
            break
        if provider in avoid_providers:
            continue
        pool = [s for s in by_provider.get(provider, []) if all(test(s) for test in hard)]
        if require_credential:
            pool = [
                s for s in pool
                if s.local or (key_resolver(s.provider) if key_resolver else None) or s.key_from_env()
            ]
        if probe_local:
            from qra.ai.probe import reachable

            pool = [s for s in pool if not s.local or reachable(s)]
        if not pool:
            continue
        out.append(sorted(pool, key=lambda s: _score(s, tier, soft))[0])
    return out


class Router:
    """One router per research run. Holds the attempt log and the budget.

    ``key_resolver`` is the BYOK seam (WP-12): given a provider name it returns
    a decrypted key for this principal, or ``None`` to fall through to the
    environment. The router never sees where the key came from and never logs it.
    """

    def __init__(
        self,
        *,
        key_resolver: Callable[[str], str | None] | None = None,
        base_url_resolver: Callable[[str], str | None] | None = None,
        budget: RunBudget | None = None,
        session=None,
        run_id: str | None = None,
        use_cache: bool = True,
    ):
        self.key_resolver = key_resolver
        self.base_url_resolver = base_url_resolver
        self.budget = budget
        self.session = session
        self.run_id = run_id
        self.use_cache = use_cache
        self.attempts: list[Attempt] = []
        self.served: dict[str, str] = {}  # role -> provider that answered

    # --- construction ------------------------------------------------------

    def _key(self, provider: str) -> str | None:
        return self.key_resolver(provider) if self.key_resolver else None

    def _adapter(self, spec: ModelSpec):
        return build(
            spec,
            api_key=self._key(spec.provider),
            base_url=self.base_url_resolver(spec.provider) if self.base_url_resolver else None,
        )

    def _avoid_for(self, role: str) -> tuple[str, ...]:
        """Honour ``prefer_different_provider_than`` — the Critic should not be
        the same model that wrote the draft, or it grades its own homework."""
        other = (registry.routing_policy().get(role) or {}).get("prefer_different_provider_than")
        used = self.served.get(other) if other else None
        return (used,) if used else ()

    def plan(self, role: str, *, kind: str = "chat", probe_local: bool = False) -> list[dict]:
        """What this role would try, without trying it. Used by /meta/routing."""
        specs = candidates(
            role,
            kind=kind,
            avoid_providers=self._avoid_for(role),
            key_resolver=self._key,
            probe_local=probe_local,
        )
        return [s.to_dict() for s in specs] + [{"provider": TERMINAL, "kind": kind}]

    # --- calls -------------------------------------------------------------

    def _record(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)

    def _try(self, role: str, specs: list[ModelSpec], call, *, kind: str):
        last_error: ProviderUnavailable | None = None
        for spec in specs:
            started = time.perf_counter()
            try:
                adapter = self._adapter(spec)
                result = call(adapter, spec)
            except ProviderUnavailable as exc:
                self._record(Attempt(
                    role=role, provider=spec.provider, model=spec.id, ok=False,
                    ms=round((time.perf_counter() - started) * 1000, 2),
                    reason=exc.reason, detail=str(exc)[:300],
                ))
                last_error = exc
                # A refusal or a policy block will not resolve by retrying the
                # same prompt elsewhere any faster, but it might — so we carry
                # on down the chain and let the log show what happened.
                continue
            except BudgetExceeded:
                raise
            self._record(Attempt(
                role=role, provider=spec.provider, model=spec.id, ok=True,
                ms=round((time.perf_counter() - started) * 1000, 2),
                cost_usd=float(getattr(result, "raw", {}).get("cost_usd", 0.0) or 0.0),
            ))
            self.served[role] = spec.provider
            return result
        attempts = [a.to_dict() for a in self.attempts if a.role == role]
        raise NoModelAvailable(role, attempts) from last_error

    def chat(
        self,
        role: str,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        schema: dict | None = None,
    ) -> ChatResult:
        specs = candidates(
            role, kind="chat", avoid_providers=self._avoid_for(role), key_resolver=self._key
        )
        if not specs:
            raise NoModelAvailable(role, [a.to_dict() for a in self.attempts if a.role == role])

        def call(adapter, spec: ModelSpec) -> ChatResult:
            cache_payload = {
                "provider": spec.provider, "model": spec.id, "system": system, "user": user,
                "max_tokens": max_tokens, "temperature": temperature, "schema": schema,
            }
            if self.use_cache and self.session is not None and temperature == 0.0:
                from qra import cache

                hit = cache.get(self.session, "model_call", cache_payload)
                if hit is not None:
                    cached = ChatResult(**hit)
                    if self.budget:
                        self.budget.record(
                            provider=spec.provider, model=spec.id, role=role,
                            input_tokens=cached.input_tokens, output_tokens=cached.output_tokens,
                            cost_usd=0.0, cached=True,
                        )
                    return cached

            if self.budget is not None:
                estimate = spec.cost(estimate_tokens(system) + estimate_tokens(user), max_tokens)
                self.budget.check(estimate)

            result = adapter.chat(
                system=system, user=user, max_tokens=max_tokens,
                temperature=temperature, schema=schema,
            )
            cost = result.cost(spec)
            result.raw["cost_usd"] = round(cost, 6)
            if self.budget is not None:
                self.budget.record(
                    provider=spec.provider, model=spec.id, role=role,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                    cost_usd=cost,
                )
            if self.use_cache and self.session is not None and temperature == 0.0:
                from qra import cache

                cache.put(self.session, "model_call", cache_payload, _chat_to_dict(result))
            return result

        return self._try(role, specs, call, kind="chat")

    def chat_json(
        self,
        role: str,
        *,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int = 1500,
        required: tuple[str, ...] = (),
        repair: bool = True,
    ):
        """Structured output with one repair round (WP-13).

        Providers with native schema support are trusted; the rest are checked
        here, and a malformed answer is re-asked *once* with the error quoted
        back. If it fails again the caller gets :class:`NoModelAvailable` and
        takes its deterministic path — a half-parsed plan is not usable.
        """
        result = self.chat(role, system=system, user=user, schema=schema, max_tokens=max_tokens)
        keys = required or tuple(schema.get("required") or ())
        missing = _missing_keys(result.structured, keys)
        if missing and repair:
            result = self.chat(
                role,
                system=system,
                user=(
                    f"{user}\n\nYour previous answer was missing required field(s): "
                    f"{', '.join(missing)}. Return the complete object."
                ),
                schema=schema,
                max_tokens=max_tokens,
                temperature=0.0,
            )
            missing = _missing_keys(result.structured, keys)
        if missing:
            raise NoModelAvailable(
                role,
                [*(a.to_dict() for a in self.attempts if a.role == role),
                 {"provider": result.provider, "model": result.model, "ok": False,
                  "reason": "schema", "detail": f"missing {', '.join(missing)} after repair"}],
            )
        return result.structured

    def embed(self, texts: list[str], *, role: str = "embedding") -> EmbeddingResult:
        specs = _kind_candidates("embedding", key_resolver=self._key)
        if not specs:
            raise NoModelAvailable(role, [])
        return self._try(role, specs, lambda a, s: a.embed(texts), kind="embedding")

    def rerank(
        self, query: str, documents: list[str], *, top_k: int | None = None, role: str = "rerank"
    ) -> RerankResult:
        specs = _kind_candidates("rerank", key_resolver=self._key)
        if not specs:
            raise NoModelAvailable(role, [])
        return self._try(
            role, specs, lambda a, s: a.rerank(query, documents, top_k=top_k), kind="rerank"
        )

    def transcribe(
        self, audio: bytes, *, language: str | None = None, filename: str = "audio.wav",
        role: str = "transcription",
    ) -> TranscriptionResult:
        specs = _kind_candidates("transcription", key_resolver=self._key, language=language)
        if not specs:
            raise NoModelAvailable(role, [])
        return self._try(
            role, specs,
            lambda a, s: a.transcribe(audio, language=language, filename=filename),
            kind="transcription",
        )

    # --- reporting ---------------------------------------------------------

    def report(self) -> dict:
        return {
            "served": dict(self.served),
            "attempts": [a.to_dict() for a in self.attempts],
            "failures": [a.to_dict() for a in self.attempts if not a.ok],
            "budget": self.budget.to_dict() if self.budget else None,
        }


def _kind_candidates(
    kind: str, *, key_resolver: Callable[[str], str | None] | None = None,
    language: str | None = None,
) -> list[ModelSpec]:
    """Non-chat kinds have no role policy: local first, then whatever has a key.

    Local first is not an arbitrary default — embeddings and transcription send
    the *whole* source text to the provider, and a private manuscript or an
    unpublished lecture should not leave the machine because a hosted key
    happened to be set.
    """
    pool = registry.specs(kind)
    if language:
        pool = [s for s in pool if not s.languages or language in s.languages]
    usable = [
        s for s in pool
        if s.local or (key_resolver(s.provider) if key_resolver else None) or s.key_from_env()
    ]
    return sorted(usable, key=lambda s: (0 if s.local else 1, s.price_in))


def _missing_keys(value, keys: tuple[str, ...]) -> list[str]:
    if not isinstance(value, dict):
        return list(keys) or ["<object>"]
    return [k for k in keys if k not in value or value[k] is None]


def _chat_to_dict(result: ChatResult) -> dict:
    return {
        "text": result.text, "model": result.model, "provider": result.provider,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason, "structured": result.structured,
        "raw": result.raw,
    }


def key_resolver_for(session, principal) -> Callable[[str], str | None]:
    """BYOK (WP-12): the principal's own key, else the org's, else the env."""
    from qra.security.service import resolve_provider_key

    def resolve(provider: str) -> str | None:
        try:
            return resolve_provider_key(session, principal, provider)
        except Exception:  # noqa: BLE001 - a key store problem must not break routing
            return None

    return resolve


def default_router(session=None, principal=None, **kwargs) -> Router:
    resolver = key_resolver_for(session, principal) if session is not None and principal else None
    return Router(key_resolver=resolver, session=session, **kwargs)
