"""Corpus endpoints: surahs, ayat, morphology, roots, graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from qra import tools
from qra.db import get_session
from qra.retrieval import deterministic as det
from qra.retrieval import graph as graph_mod

router = APIRouter(prefix="/corpus", tags=["corpus"])


@router.get("/surahs")
def surahs(session: Session = Depends(get_session)) -> list[dict]:
    return det.list_surahs(session)


@router.get("/surahs/{surah}")
def surah_detail(
    surah: int,
    start: int = Query(1, ge=1),
    end: int | None = None,
    session: Session = Depends(get_session),
) -> dict:
    meta = next((s for s in det.list_surahs(session) if s["id"] == surah), None)
    if meta is None:
        raise HTTPException(404, f"surah {surah} not found")
    end = end or meta["ayah_count"]
    spans = det.get_range(session, surah, start, end)
    return {"surah": meta, "ayat": [s.to_dict() for s in spans]}


@router.get("/ayah/{surah}/{ayah}")
def ayah(
    surah: int,
    ayah: int,
    translations: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    payload = tools.get_ayah(session, surah, ayah, with_translations=translations)
    if not payload.get("found"):
        raise HTTPException(404, f"ayah {surah}:{ayah} not found")
    return payload


@router.get("/ayah/{surah}/{ayah}/morphology")
def morphology(surah: int, ayah: int, session: Session = Depends(get_session)) -> dict:
    payload = tools.get_morphology(session, surah, ayah)
    if not payload:
        raise HTTPException(404, f"ayah {surah}:{ayah} not found")
    return payload


@router.get("/ayah/{surah}/{ayah}/tafsir")
def tafsir(
    surah: int,
    ayah: int,
    editions: list[str] | None = Query(None),
    session: Session = Depends(get_session),
) -> dict:
    return tools.get_tafsir(session, surah, ayah, editions=editions)


@router.get("/ayah/{surah}/{ayah}/hadith")
def hadith(surah: int, ayah: int, session: Session = Depends(get_session)) -> dict:
    return tools.get_hadith_for_ayah(session, surah, ayah)


@router.get("/ayah/{surah}/{ayah}/graph")
def ayah_graph(surah: int, ayah: int, session: Session = Depends(get_session)) -> dict:
    payload = tools.ayah_graph(session, surah, ayah)
    if not payload:
        raise HTTPException(404, f"ayah {surah}:{ayah} not found")
    return payload


@router.get("/ayah/{surah}/{ayah}/similar")
def similar(surah: int, ayah: int, session: Session = Depends(get_session)) -> dict:
    return tools.similar_ayat(session, surah, ayah)


@router.get("/roots/{root}")
def root_profile(root: str, session: Session = Depends(get_session)) -> dict:
    payload = tools.get_root_profile(session, root)
    if not payload.get("found"):
        raise HTTPException(404, f"root {root} not found in the corpus")
    return payload


@router.get("/roots/{root}/partners")
def root_partners(
    root: str, scope: str = "ayah", limit: int = 20, session: Session = Depends(get_session)
) -> dict:
    return tools.top_cooccurrences(session, root, scope=scope, limit=limit)


@router.get("/concepts")
def concepts(session: Session = Depends(get_session)) -> list[dict]:
    from qra.workspace.service import concept_index

    return concept_index(session)


@router.get("/concepts/{slug}")
def concept(slug: str, session: Session = Depends(get_session)) -> dict:
    payload = graph_mod.concept_expansion(session, slug)
    if not payload:
        raise HTTPException(404, f"concept {slug} not found")
    return payload


@router.get("/concepts-map")
def concept_map(min_shared: int = 3, session: Session = Depends(get_session)) -> dict:
    return graph_mod.concept_map(session, min_shared=min_shared)
