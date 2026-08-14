"""Semantic retrieval — multilingual embeddings + optional cross-encoder rerank.

Off by default. With no ``QRA_EMBEDDING_PROVIDER`` configured, every entry point
here raises :class:`SemanticUnavailable` and the API reports the mode as
disabled. That is deliberate: a hash-based stand-in would return plausible
nonsense, and on this corpus plausible nonsense is worse than an honest "not
configured".

Storage: pgvector when the extension exists, otherwise a float array plus
brute-force cosine. At 6,236 ayat and ~25k translation rows the brute-force path
is milliseconds, so the extension is an optimisation, never a requirement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from qra.config import settings
from qra.models import Embedding, SearchDoc
from qra.retrieval.base import CorpusFilter, Span
from qra.retrieval.lexical import LexicalHit, _hydrate


class SemanticUnavailable(RuntimeError):
    """Raised when semantic search is requested but no provider is configured."""


@dataclass
class EmbeddingProvider:
    """Thin adapter over an embedding endpoint.

    ``ollama`` targets a local box (BGE-M3 or multilingual-e5 — both put Arabic,
    Urdu and English in one space, which is the requirement here);
    ``openai_compatible`` targets any ``/v1/embeddings`` service.
    """

    provider: str
    model: str
    base_url: str
    api_key: str | None = None
    dim: int = 1024

    @classmethod
    def from_settings(cls) -> EmbeddingProvider:
        if not settings.semantic_enabled:
            raise SemanticUnavailable(
                "Semantic retrieval is not configured. Set QRA_EMBEDDING_PROVIDER "
                "(ollama|openai_compatible), QRA_EMBEDDING_MODEL and QRA_EMBEDDING_BASE_URL. "
                "Deterministic and lexical retrieval work without it."
            )
        base = settings.embedding_base_url or settings.ollama_base_url or "http://localhost:11434"
        return cls(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            base_url=base.rstrip("/"),
            api_key=settings.embedding_api_key,
            dim=settings.embedding_dim,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "ollama":
            out = []
            with httpx.Client(timeout=120.0) as client:
                for text in texts:
                    response = client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                    )
                    response.raise_for_status()
                    out.append(response.json()["embedding"])
            return out
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with httpx.Client(timeout=120.0, headers=headers) as client:
            response = client.post(
                f"{self.base_url}/v1/embeddings", json={"model": self.model, "input": texts}
            )
            response.raise_for_status()
            return [item["embedding"] for item in response.json()["data"]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def build_embeddings(
    session: Session, *, kinds: tuple[str, ...] = ("ayah",), batch_size: int = 32
) -> dict:
    provider = EmbeddingProvider.from_settings()
    docs = session.scalars(select(SearchDoc).where(SearchDoc.kind.in_(kinds))).all()
    session.execute(
        delete(Embedding).where(
            Embedding.doc_id.in_([d.id for d in docs]), Embedding.model == provider.model
        )
    )
    written = 0
    for offset in range(0, len(docs), batch_size):
        batch = docs[offset : offset + batch_size]
        vectors = provider.embed([d.text for d in batch])
        session.execute(
            insert(Embedding),
            [
                {
                    "doc_id": doc.id,
                    "model": provider.model,
                    "dim": len(vector),
                    "vector": vector,
                }
                for doc, vector in zip(batch, vectors, strict=True)
            ],
        )
        written += len(batch)
        session.commit()
    return {"model": provider.model, "docs": written}


def search_semantic(
    session: Session,
    query: str,
    *,
    kinds: tuple[str, ...] = ("ayah",),
    filters: CorpusFilter | None = None,
    limit: int = 20,
    candidate_pool: int = 200,
) -> list[Span]:
    """Embed the query, score every stored vector, return the top spans.

    Exhaustive over the vector store rather than ANN-approximate — again,
    because the corpus is small enough that approximation buys nothing.
    """
    provider = EmbeddingProvider.from_settings()
    (query_vector,) = provider.embed([query])

    rows = session.execute(
        select(Embedding.doc_id, Embedding.vector, SearchDoc.kind, SearchDoc.ref_id, SearchDoc.ayah_id, SearchDoc.edition_id)
        .join(SearchDoc, SearchDoc.id == Embedding.doc_id)
        .where(Embedding.model == provider.model, SearchDoc.kind.in_(kinds))
    ).all()
    if not rows:
        raise SemanticUnavailable(
            f"No embeddings stored for model {provider.model}. Run `qra embed` first."
        )

    scored = [
        LexicalHit(
            doc_id=doc_id,
            kind=kind,
            ref_id=ref_id,
            ayah_id=ayah_id,
            edition_id=edition_id,
            score=_cosine(query_vector, vector),
            matched_terms=[],
        )
        for doc_id, vector, kind, ref_id, ayah_id, edition_id in rows
    ]
    scored.sort(key=lambda h: h.score, reverse=True)
    spans = _hydrate(session, scored[:candidate_pool])
    for span in spans:
        span.retrieval_mode = "semantic"

    if filters and not filters.is_empty:
        from qra.models import Ayah

        allowed = {aid for (aid,) in session.execute(filters.apply(select(Ayah.id))).all()}
        spans = [s for s in spans if s.ayah_id is None or s.ayah_id in allowed]
    return spans[:limit]


def rerank(query: str, spans: list[Span], *, top_k: int = 10) -> list[Span]:
    """Cross-encoder rerank hook.

    Left as an explicit no-op with a marker rather than a fake implementation:
    when you wire a reranker (bge-reranker-v2-m3 on the local box is the obvious
    choice), replace the body and the marker disappears from results.
    """
    for span in spans:
        span.extra.setdefault("reranked", False)
    return spans[:top_k]


def status() -> dict:
    return {
        "enabled": settings.semantic_enabled,
        "provider": settings.embedding_provider,
        "model": settings.embedding_model if settings.semantic_enabled else None,
        "reason": None
        if settings.semantic_enabled
        else "QRA_EMBEDDING_PROVIDER not set; deterministic and lexical retrieval are unaffected",
    }
