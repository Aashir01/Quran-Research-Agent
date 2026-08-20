"""Provider interfaces (WP-09).

Four kinds, four protocols. The design goal is that **no provider is
load-bearing**: adding one is a new adapter file plus a config block, and
removing every provider leaves a system that still retrieves, counts, tests
hypotheses and verifies citations.

Adapters raise :class:`ProviderUnavailable` rather than returning something
plausible. That distinction is the whole reason this layer exists — the router
can only fall back correctly if failure is unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from qra.ai.registry import ModelSpec


class ProviderUnavailable(RuntimeError):
    """This provider cannot serve the call. Carries why, for the fallback log."""

    def __init__(self, message: str, *, reason: str = "unavailable", provider: str = ""):
        super().__init__(message)
        # rate_limit | timeout | refusal | unavailable | no_credential | policy
        self.reason = reason
        self.provider = provider


class ProviderRefusal(ProviderUnavailable):
    """The model declined. Distinct from a failure — retrying elsewhere is fair,
    but the refusal is recorded rather than hidden."""

    def __init__(self, message: str, *, provider: str = ""):
        super().__init__(message, reason="refusal", provider=provider)


@dataclass
class ChatResult:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    structured: Any = None
    raw: dict = field(default_factory=dict)

    def cost(self, spec: ModelSpec) -> float:
        return spec.cost(self.input_tokens, self.output_tokens)


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider: str
    dim: int
    input_tokens: int = 0


@dataclass
class RerankResult:
    """Indices into the input list, best first, with scores."""

    order: list[int]
    scores: list[float]
    model: str
    provider: str


@dataclass
class TranscriptionResult:
    text: str
    language: str
    model: str
    provider: str
    segments: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0


@runtime_checkable
class ChatProvider(Protocol):
    spec: ModelSpec

    def chat(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        schema: dict | None = None,
    ) -> ChatResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    spec: ModelSpec

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


@runtime_checkable
class RerankProvider(Protocol):
    spec: ModelSpec

    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None) -> RerankResult: ...


@runtime_checkable
class TranscriptionProvider(Protocol):
    spec: ModelSpec

    def transcribe(self, audio: bytes, *, language: str | None = None, filename: str = "audio.wav") -> TranscriptionResult: ...


def estimate_tokens(text: str) -> int:
    """Rough token count for budgeting before a call.

    Deliberately crude and deliberately *over*-estimating for Arabic and Urdu,
    which tokenise far worse than English on most vocabularies. A budget that
    under-estimates is a budget that gets exceeded.
    """
    if not text:
        return 0
    non_latin = sum(1 for ch in text if ord(ch) > 0x0590)
    latin = len(text) - non_latin
    return int(latin / 4 + non_latin / 1.6) + 1
