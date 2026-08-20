"""Rerank adapters (WP-15).

Reranking reorders a *ranked* result set. It must never touch an exhaustive one:
if a query is answered by "every occurrence of this root", the order is the
mushaf's and a model has no business changing it, and any subsetting would make
the exhaustiveness claim false.

That rule is enforced at the type level in :mod:`qra.ai.rerank_guard`, not by
convention here.
"""

from __future__ import annotations

from qra.ai.adapters._http import DEFAULT_TIMEOUT, LOCAL_TIMEOUT, post, require_key
from qra.ai.base import ProviderUnavailable, RerankResult
from qra.ai.registry import ModelSpec

_LOCAL_CACHE: dict[str, object] = {}


class _Base:
    def __init__(self, spec: ModelSpec, *, api_key: str | None = None, base_url: str | None = None):
        self.spec = spec
        self.api_key = api_key
        self.base_url = (base_url or spec.base_url or "").rstrip("/")
        self.timeout = LOCAL_TIMEOUT if spec.local else DEFAULT_TIMEOUT

    @property
    def name(self) -> str:
        return f"{self.spec.provider}/{self.spec.id}"

    @staticmethod
    def _empty(spec: ModelSpec) -> RerankResult:
        return RerankResult([], [], spec.id, spec.provider)


class CohereRerank(_Base):
    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None) -> RerankResult:
        if not documents:
            return self._empty(self.spec)
        body = {"model": self.spec.id, "query": query, "documents": documents,
                "top_n": top_k or len(documents)}
        payload = post(
            f"{self.base_url}/rerank",
            provider=self.spec.provider,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {require_key(self.spec, self.api_key)}",
            },
            json_body=body,
            timeout=self.timeout,
        )
        rows = payload.get("results", [])
        return RerankResult(
            order=[r["index"] for r in rows],
            scores=[float(r.get("relevance_score", 0.0)) for r in rows],
            model=self.spec.id,
            provider=self.spec.provider,
        )


class JinaRerank(_Base):
    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None) -> RerankResult:
        if not documents:
            return self._empty(self.spec)
        payload = post(
            f"{self.base_url}/rerank",
            provider=self.spec.provider,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {require_key(self.spec, self.api_key)}",
            },
            json_body={"model": self.spec.id, "query": query, "documents": documents,
                       "top_n": top_k or len(documents)},
            timeout=self.timeout,
        )
        rows = payload.get("results", [])
        return RerankResult(
            order=[r["index"] for r in rows],
            scores=[float(r.get("relevance_score", 0.0)) for r in rows],
            model=self.spec.id,
            provider=self.spec.provider,
        )


class CrossEncoderRerank(_Base):
    """Local cross-encoder. The multilingual one matters here: an English-only
    reranker on Urdu tafsir is worse than no reranker, because it looks like it
    worked."""

    def _model(self):
        cached = _LOCAL_CACHE.get(self.spec.id)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderUnavailable(
                f"{self.name} needs sentence-transformers (pip install 'qra[local-models]')",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        try:
            model = CrossEncoder(self.spec.id)
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(
                f"could not load {self.spec.id}: {exc}",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        _LOCAL_CACHE[self.spec.id] = model
        return model

    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None) -> RerankResult:
        if not documents:
            return self._empty(self.spec)
        scores = [float(s) for s in self._model().predict([(query, d) for d in documents])]
        order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
        if top_k:
            order = order[:top_k]
        return RerankResult(
            order=order,
            scores=[scores[i] for i in order],
            model=self.spec.id,
            provider=self.spec.provider,
        )


RERANK_ADAPTERS: dict[str, type[_Base]] = {
    "cohere": CohereRerank,
    "jina": JinaRerank,
    "sentence_transformers": CrossEncoderRerank,
}
