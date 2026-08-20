"""Embedding adapters (WP-14).

Semantic retrieval is the one mode that can be *wrong* rather than merely
incomplete, so it stays optional and clearly labelled. These adapters exist to
make it swappable, not to make it default.

Dimension is checked against the registry on every call. A provider that
quietly changes vector width would corrupt an index that no query would ever
report as broken — the failure would look like bad recall, not a bug.
"""

from __future__ import annotations

from qra.ai.adapters._http import DEFAULT_TIMEOUT, LOCAL_TIMEOUT, post, require_key
from qra.ai.base import EmbeddingResult, ProviderUnavailable
from qra.ai.registry import ModelSpec

# Sentence-transformers models are expensive to construct; one per id per process.
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

    def _check_dim(self, vectors: list[list[float]]) -> int:
        dim = len(vectors[0]) if vectors else (self.spec.dim or 0)
        if self.spec.dim and dim != self.spec.dim:
            raise ProviderUnavailable(
                f"{self.name} returned {dim}-dimensional vectors, registry says {self.spec.dim}. "
                "Refusing to write mixed-width vectors into the index.",
                reason="policy",
                provider=self.spec.provider,
            )
        return dim


class OpenAIEmbedding(_Base):
    """OpenAI, Jina and anything else speaking ``/embeddings``."""

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.spec.id, self.spec.provider, self.spec.dim or 0)
        payload = post(
            f"{self.base_url}/embeddings",
            provider=self.spec.provider,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {require_key(self.spec, self.api_key)}",
            },
            json_body={"model": self.spec.id, "input": texts},
            timeout=self.timeout,
        )
        rows = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
        vectors = [r["embedding"] for r in rows]
        return EmbeddingResult(
            vectors=vectors,
            model=self.spec.id,
            provider=self.spec.provider,
            dim=self._check_dim(vectors),
            input_tokens=payload.get("usage", {}).get("prompt_tokens", 0),
        )


class VoyageEmbedding(_Base):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.spec.id, self.spec.provider, self.spec.dim or 0)
        payload = post(
            f"{self.base_url}/embeddings",
            provider=self.spec.provider,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {require_key(self.spec, self.api_key)}",
            },
            json_body={"model": self.spec.id, "input": texts, "input_type": "document"},
            timeout=self.timeout,
        )
        rows = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
        vectors = [r["embedding"] for r in rows]
        return EmbeddingResult(
            vectors, self.spec.id, self.spec.provider, self._check_dim(vectors),
            payload.get("usage", {}).get("total_tokens", 0),
        )


class CohereEmbedding(_Base):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.spec.id, self.spec.provider, self.spec.dim or 0)
        payload = post(
            f"{self.base_url}/embed",
            provider=self.spec.provider,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {require_key(self.spec, self.api_key)}",
            },
            json_body={
                "model": self.spec.id,
                "texts": texts,
                "input_type": "search_document",
                "embedding_types": ["float"],
            },
            timeout=self.timeout,
        )
        embeddings = payload.get("embeddings", {})
        vectors = embeddings.get("float") if isinstance(embeddings, dict) else embeddings
        vectors = vectors or []
        return EmbeddingResult(
            vectors, self.spec.id, self.spec.provider, self._check_dim(vectors),
            payload.get("meta", {}).get("billed_units", {}).get("input_tokens", 0),
        )


class GoogleEmbedding(_Base):
    """Gemini embeds one text per request, so batching is ours to do."""

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.spec.id, self.spec.provider, self.spec.dim or 0)
        base = self.base_url or "https://generativelanguage.googleapis.com/v1beta"
        payload = post(
            f"{base}/models/{self.spec.id}:batchEmbedContents",
            provider=self.spec.provider,
            headers={
                "content-type": "application/json",
                "x-goog-api-key": require_key(self.spec, self.api_key),
            },
            json_body={
                "requests": [
                    {"model": f"models/{self.spec.id}", "content": {"parts": [{"text": t}]}}
                    for t in texts
                ]
            },
            timeout=self.timeout,
        )
        vectors = [e.get("values", []) for e in payload.get("embeddings", [])]
        return EmbeddingResult(
            vectors, self.spec.id, self.spec.provider, self._check_dim(vectors)
        )


class OllamaEmbedding(_Base):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.spec.id, self.spec.provider, self.spec.dim or 0)
        payload = post(
            f"{self.base_url or 'http://localhost:11434'}/api/embed",
            provider=self.spec.provider,
            json_body={"model": self.spec.id, "input": texts},
            timeout=self.timeout,
        )
        vectors = payload.get("embeddings") or []
        return EmbeddingResult(
            vectors, self.spec.id, self.spec.provider, self._check_dim(vectors),
            payload.get("prompt_eval_count", 0),
        )


class SentenceTransformerEmbedding(_Base):
    """Fully local. No key, no network, no per-token cost."""

    def _model(self):
        cached = _LOCAL_CACHE.get(self.spec.id)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as exc:
            raise ProviderUnavailable(
                f"{self.name} needs sentence-transformers "
                "(pip install 'qra[local-models]'); semantic retrieval stays off until then",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        try:
            model = SentenceTransformer(self.spec.id)
        except Exception as exc:  # noqa: BLE001 - download or disk failure
            raise ProviderUnavailable(
                f"could not load {self.spec.id}: {exc}",
                reason="unavailable",
                provider=self.spec.provider,
            ) from exc
        _LOCAL_CACHE[self.spec.id] = model
        return model

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], self.spec.id, self.spec.provider, self.spec.dim or 0)
        vectors = [list(map(float, v)) for v in self._model().encode(texts, normalize_embeddings=True)]
        return EmbeddingResult(
            vectors, self.spec.id, self.spec.provider, self._check_dim(vectors)
        )


EMBEDDING_ADAPTERS: dict[str, type[_Base]] = {
    "openai": OpenAIEmbedding,
    "voyage": VoyageEmbedding,
    "cohere": CohereEmbedding,
    "google": GoogleEmbedding,
    "ollama": OllamaEmbedding,
    "sentence_transformers": SentenceTransformerEmbedding,
}
