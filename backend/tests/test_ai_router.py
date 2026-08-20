"""Provider layer: registry, routing, fallback, structured output, rerank guard.

These run with no database and no credentials, which is the point — the
behaviour under test is what happens when providers are *absent*.
"""

from __future__ import annotations

import pytest

from qra.ai import registry
from qra.ai.adapters import coverage
from qra.ai.base import ChatResult, ProviderUnavailable, RerankResult, estimate_tokens
from qra.ai.registry import ModelSpec
from qra.ai.rerank_guard import ExhaustiveResultError, as_ranked, rerank_spans
from qra.ai.router import NoModelAvailable, Router, candidates
from qra.citations import Citation
from qra.retrieval.base import Span


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch):
    """Credentials on the developer's machine must not change these results."""
    import os

    for var in list(os.environ):
        if var.endswith("_API_KEY") or var.startswith("AWS_") or var.startswith("GOOGLE_"):
            monkeypatch.delenv(var, raising=False)


# --- registry --------------------------------------------------------------


def test_no_model_id_is_hardcoded_outside_the_registry():
    """WP-09: the registry is the only place a model id appears."""
    from pathlib import Path

    root = Path(registry.__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        if "ai/registry" in str(path) or "/tests/" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("claude-opus-5", "gpt-5", "gemini-2.5-pro", "deepseek-chat"):
            # A docstring may mention one; an assignment may not.
            for line in text.splitlines():
                if needle in line and "#" not in line.split(needle)[0] and "=" in line:
                    offenders.append(f"{path.name}: {line.strip()[:80]}")
    assert not offenders, f"model ids leaked into code: {offenders}"


def test_every_registry_entry_has_an_adapter():
    """A config block with no adapter fails midway through a research run."""
    report = coverage()
    assert report["missing"] == []
    assert report["covered"] >= 40


def test_every_fallback_chain_ends_in_deterministic():
    for tier, chain in registry.fallback_chains().items():
        assert chain[-1] == "deterministic", f"{tier} chain ends in {chain[-1]!r}"


def test_stale_verified_on_is_reported_not_fatal():
    old = ModelSpec(provider="p", kind="chat", id="m", api="openai", verified_on="2000-01-01")
    assert old.stale and old.age_days > 180
    fresh = ModelSpec(provider="p", kind="chat", id="m", api="openai", verified_on=None)
    assert not fresh.stale and fresh.age_days is None


# --- routing ---------------------------------------------------------------


def test_role_routing_respects_tier(monkeypatch):
    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "sk-test")
    assert candidates("planner")[0].tier == "reasoning"
    assert candidates("hadith")[0].tier in ("fast", "balanced")


def test_hard_needs_filter_candidates(monkeypatch):
    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "sk-test")
    for spec in candidates("planner"):  # needs long_context + structured_output
        assert (spec.context or 0) >= 100_000
        assert spec.structured_output != "none"


def test_critic_avoids_the_providers_that_drafted(monkeypatch):
    """A Critic on the same model that wrote the draft grades its own homework."""
    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("QRA_OPENAI_API_KEY", "sk-test")
    router = Router()
    router.served["scribe"] = "anthropic"
    providers = [c["provider"] for c in router.plan("critic")]
    assert "anthropic" not in providers
    assert providers[-1] == "deterministic"


def test_no_credentials_means_no_model_not_a_guess():
    """WP-11: with every provider unreachable the caller is told, not fudged."""
    router = Router()
    with pytest.raises(NoModelAvailable) as excinfo:
        router.chat("planner", system="s", user="u")
    message = str(excinfo.value)
    assert "deterministic" in message
    assert "citation verification" in message


def test_fallback_walks_the_chain_and_logs_every_attempt(monkeypatch):
    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("QRA_OPENAI_API_KEY", "sk-test")
    router = Router()
    calls = []

    class Fake:
        def __init__(self, spec):
            self.spec = spec

        def chat(self, **kwargs):
            calls.append(self.spec.provider)
            if self.spec.provider == "anthropic":
                raise ProviderUnavailable("429", reason="rate_limit", provider="anthropic")
            return ChatResult(text="ok", model=self.spec.id, provider=self.spec.provider)

    monkeypatch.setattr(router, "_adapter", lambda spec: Fake(spec))
    result = router.chat("planner", system="s", user="u")

    assert result.provider == "openai"
    assert calls[0] == "anthropic"
    failures = router.report()["failures"]
    assert failures[0]["reason"] == "rate_limit"
    assert router.report()["served"]["planner"] == "openai"


def test_structured_output_repairs_once_then_gives_up(monkeypatch):
    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "sk-test")
    router = Router()
    schema = {"type": "object", "required": ["sub_questions"]}

    class Fake:
        def __init__(self, spec):
            self.spec = spec

        def chat(self, **kwargs):
            return ChatResult(
                text="{}", model=self.spec.id, provider=self.spec.provider, structured={}
            )

    monkeypatch.setattr(router, "_adapter", lambda spec: Fake(spec))
    with pytest.raises(NoModelAvailable) as excinfo:
        router.chat_json("planner", system="s", user="u", schema=schema)
    assert "sub_questions" in str(excinfo.value.attempts[-1]["detail"])


def test_budget_is_checked_before_the_call_not_after(monkeypatch):
    from qra.budget import BudgetExceeded, RunBudget

    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "sk-test")
    budget = RunBudget(run_id="r", ceiling_usd=0.0)
    router = Router(budget=budget)
    called = []

    class Fake:
        def __init__(self, spec):
            self.spec = spec

        def chat(self, **kwargs):
            called.append(1)
            return ChatResult(text="x", model=self.spec.id, provider=self.spec.provider)

    monkeypatch.setattr(router, "_adapter", lambda spec: Fake(spec))
    with pytest.raises(BudgetExceeded):
        router.chat("planner", system="s", user="u", max_tokens=1000)
    assert called == [], "the ceiling must stop the call, not report it afterwards"


def test_byok_key_beats_the_environment(monkeypatch):
    monkeypatch.setenv("QRA_ANTHROPIC_API_KEY", "env-key")
    seen = {}

    class Fake:
        def __init__(self, spec, api_key=None, base_url=None):
            self.spec = spec
            seen["key"] = api_key

        def chat(self, **kwargs):
            return ChatResult(text="ok", model=self.spec.id, provider=self.spec.provider)

    monkeypatch.setattr("qra.ai.router.build", lambda spec, api_key=None, base_url=None: Fake(
        spec, api_key=api_key, base_url=base_url))
    router = Router(key_resolver=lambda provider: "user-key")
    router.chat("planner", system="s", user="u")
    assert seen["key"] == "user-key"


# --- token estimation ------------------------------------------------------


def test_arabic_is_estimated_as_costlier_than_english():
    """Budgets that under-estimate are budgets that get exceeded."""
    english = estimate_tokens("the quick brown fox jumps over")
    arabic = estimate_tokens("الحمد لله رب العالمين الرحمن")
    assert arabic > english


# --- rerank guard (WP-15) --------------------------------------------------


def _span(mode: str, text: str = "x") -> Span:
    return Span(kind="ayah", text=text, citation=Citation(kind="ayah", ref="2:255"), retrieval_mode=mode)


def test_exhaustive_results_cannot_be_reranked():
    spans = [_span("deterministic"), _span("deterministic")]
    with pytest.raises(ExhaustiveResultError) as excinfo:
        as_ranked(spans)
    assert "silently drop" in str(excinfo.value)


def test_a_bare_list_cannot_be_passed_to_rerank_spans():
    """The check has one door; passing a list must not route around it."""
    with pytest.raises(ExhaustiveResultError):
        rerank_spans("q", [_span("lexical")], provider=None)


def test_ranked_results_rerank_and_keep_the_original_score():
    spans = [_span("lexical", "a"), _span("lexical", "b")]
    spans[0].score, spans[1].score = 9.0, 1.0

    class FakeReranker:
        def rerank(self, query, documents, top_k=None):
            return RerankResult(order=[1, 0], scores=[0.9, 0.2], model="m", provider="p")

    out = rerank_spans("q", as_ranked(spans), provider=FakeReranker())
    assert [s.text for s in out] == ["b", "a"]
    assert out[0].extra["pre_rerank_score"] == 1.0  # disagreement stays visible
    assert out[0].retrieval_mode == "lexical+rerank"
