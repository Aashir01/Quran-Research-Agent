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

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from qra.ai.base import ProviderUnavailable
from qra.ai.rerank_guard import ExhaustiveResultError, as_ranked, rerank_spans
from qra.config import settings
from qra.models import Embedding, SearchDoc
from qra.retrieval.base import CorpusFilter, Span
from qra.retrieval.lexical import LexicalHit, _hydrate


class SemanticUnavailable(RuntimeError):
    """Raised when semantic search is requested but no provider is configured."""


def embedder():
    """The configured embedding adapter, or an honest refusal.

    Which provider serves this is registry policy (WP-14), not a hardcoded
    client: ``QRA_EMBEDDING_PROVIDER`` names a block in ``config/models.yaml``
    and :mod:`qra.ai.adapters` supplies the wire protocol. Local providers are
    preferred when the setting is absent-but-permissive because embedding sends
    the *whole* text to whoever serves it.
    """
    if not settings.semantic_enabled:
        raise SemanticUnavailable(
            "Semantic retrieval is not configured. Set QRA_EMBEDDING_PROVIDER to a provider "
            "in config/models.yaml (bge_m3_local, ollama, openai, voyage, cohere, google, jina). "
            "Deterministic and lexical retrieval work without it."
        )
    from qra.ai import registry
    from qra.ai.adapters import build

    spec = registry.find("embedding", settings.embedding_provider, settings.embedding_model)
    if spec is None:
        available = ", ".join(registry.providers("embedding"))
        raise SemanticUnavailable(
            f"embedding provider {settings.embedding_provider!r} is not in the registry "
            f"(have: {available})"
        )
    try:
        return build(spec)
    except ProviderUnavailable as exc:
        raise SemanticUnavailable(str(exc)) from exc


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def build_embeddings(
    session: Session, *, kinds: tuple[str, ...] = ("ayah",), batch_size: int = 32
) -> dict:
    provider = embedder()
    model_id = provider.spec.id
    docs = session.scalars(select(SearchDoc).where(SearchDoc.kind.in_(kinds))).all()
    session.execute(
        delete(Embedding).where(
            Embedding.doc_id.in_([d.id for d in docs]), Embedding.model == model_id
        )
    )
    written = 0
    for offset in range(0, len(docs), batch_size):
        batch = docs[offset : offset + batch_size]
        vectors = provider.embed([d.text for d in batch]).vectors
        session.execute(
            insert(Embedding),
            [
                {
                    "doc_id": doc.id,
                    "model": model_id,
                    "dim": len(vector),
                    "vector": vector,
                }
                for doc, vector in zip(batch, vectors, strict=True)
            ],
        )
        written += len(batch)
        session.commit()
    return {"model": model_id, "provider": provider.spec.provider, "docs": written}


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
    provider = embedder()
    model_id = provider.spec.id
    (query_vector,) = provider.embed([query]).vectors

    rows = session.execute(
        select(Embedding.doc_id, Embedding.vector, SearchDoc.kind, SearchDoc.ref_id, SearchDoc.ayah_id, SearchDoc.edition_id)
        .join(SearchDoc, SearchDoc.id == Embedding.doc_id)
        .where(Embedding.model == model_id, SearchDoc.kind.in_(kinds))
    ).all()
    if not rows:
        raise SemanticUnavailable(
            f"No embeddings stored for model {model_id}. Run `qra embed` first."
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


def rerank(query: str, spans: list[Span], *, top_k: int = 10, router=None) -> list[Span]:
    """Cross-encoder rerank over *ranked* spans (WP-15).

    Two rules are enforced rather than documented. Exhaustive spans are refused
    outright by :func:`qra.ai.rerank_guard.as_ranked` — reordering "every
    occurrence of this root" would falsify the claim attached to it, and a
    ``top_k`` would drop members of a set the caller was told was complete. And
    when no reranker is configured the spans come back untouched with
    ``reranked: False`` on each, because a silent no-op that looks like a rerank
    is how a pipeline starts lying about its own quality.
    """
    if not spans:
        return []
    try:
        ranked = as_ranked(spans)
    except ExhaustiveResultError:
        raise
    from qra.ai.router import NoModelAvailable, Router

    active = router or Router()
    try:
        provider = _rerank_provider(active)
    except NoModelAvailable as exc:
        for span in spans:
            span.extra.setdefault("reranked", False)
            span.extra.setdefault("rerank_unavailable", str(exc)[:200])
        return spans[:top_k]
    out = rerank_spans(query, ranked, provider=provider, top_k=top_k)
    for span in out:
        span.extra["reranked"] = True
    return out


def _rerank_provider(router):
    """A rerank adapter, or :class:`NoModelAvailable`. Local models first: a
    reranker sees the full text of every candidate, same as an embedder."""
    from qra.ai.adapters import build
    from qra.ai.router import NoModelAvailable, _kind_candidates

    specs = _kind_candidates("rerank", key_resolver=router._key)
    for spec in specs:
        try:
            return build(spec, api_key=router._key(spec.provider))
        except ProviderUnavailable:
            continue
    raise NoModelAvailable("rerank", [])


def status() -> dict:
    return {
        "enabled": settings.semantic_enabled,
        "provider": settings.embedding_provider,
        "model": settings.embedding_model,
        "reason": None
        if settings.semantic_enabled
        else "QRA_EMBEDDING_PROVIDER not set; deterministic and lexical retrieval are unaffected",
    }
