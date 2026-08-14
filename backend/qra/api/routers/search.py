"""Search endpoints — one route per retrieval mode, never blended.

``/search/root`` and ``/search/phrase`` are exhaustive and say so in the
payload. ``/search/text`` is ranked and says that too. ``/search/semantic``
returns 503 with a reason when no embedding provider is configured, rather than
quietly falling back to a different mode and reporting it as semantic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from qra import tools
from qra.db import get_session
from qra.retrieval import semantic as semantic_mod
from qra.retrieval.base import CorpusFilter
from qra.retrieval.deterministic import MorphologyFilter, search_morphology

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/root")
def by_root(
    root: str,
    revelation_place: str | None = None,
    surahs: list[int] | None = Query(None),
    pos_class: str | None = None,
    aspect: str | None = None,
    verb_form: str | None = None,
    derivation: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """Every occurrence of a root. Accepts ``علم``, ``ع-ل-م`` or Buckwalter ``Elm``."""
    return tools.search_root(
        session,
        root,
        revelation_place=revelation_place,
        surahs=surahs,
        pos_class=pos_class,
        aspect=aspect,
        verb_form=verb_form,
        derivation=derivation,
        limit=limit,
    )


@router.get("/phrase")
def by_phrase(
    phrase: str,
    ignore_diacritics: bool = True,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    return tools.search_phrase(session, phrase, ignore_diacritics=ignore_diacritics, limit=limit)


@router.get("/morphology")
def by_morphology(
    pos_class: str | None = None,
    tag: str | None = None,
    aspect: str | None = None,
    verb_form: str | None = None,
    mood: str | None = None,
    voice: str | None = None,
    case: str | None = None,
    derivation: str | None = None,
    root: str | None = None,
    revelation_place: str | None = None,
    surahs: list[int] | None = Query(None),
    limit: int = 100,
    session: Session = Depends(get_session),
) -> dict:
    """e.g. every imperative verb from root ق-و-ل in Makki surahs."""
    return search_morphology(
        session,
        filters=CorpusFilter(revelation_place=revelation_place, surahs=surahs),
        morphology=MorphologyFilter(
            pos_class=pos_class,
            tag=tag,
            aspect=aspect,
            verb_form=verb_form,
            mood=mood,
            voice=voice,
            case=case,
            derivation=derivation,
        ),
        root=root,
        limit=limit,
    ).to_dict()


@router.get("/count")
def count(
    root: str | None = None,
    lemma: str | None = None,
    phrase: str | None = None,
    revelation_place: str | None = None,
    surahs: list[int] | None = Query(None),
    session: Session = Depends(get_session),
) -> dict:
    if not any((root, lemma, phrase)):
        raise HTTPException(400, "supply one of root, lemma or phrase")
    return tools.count_occurrences(
        session,
        root=root,
        lemma=lemma,
        phrase=phrase,
        revelation_place=revelation_place,
        surahs=surahs,
    )


@router.get("/text")
def lexical(
    q: str,
    language: str | None = None,
    include_tafsir: bool = False,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    """BM25 over translations (and optionally tafsir). Ranked, not exhaustive."""
    return tools.search_translations(
        session, q, language=language, include_tafsir=include_tafsir, limit=limit
    )


@router.get("/semantic")
def semantic(
    q: str,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    try:
        spans = semantic_mod.search_semantic(session, q, limit=limit)
    except semantic_mod.SemanticUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "query": q,
        "mode": "semantic",
        "exhaustive": False,
        "results": [s.to_dict() for s in spans],
    }


@router.get("/semantic/status")
def semantic_status() -> dict:
    return semantic_mod.status()
