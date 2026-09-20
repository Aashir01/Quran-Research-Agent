"""Rijal: the narrators, and the graph their chains form (Track I).

Mounted on its own prefix rather than under ``/hadith``. ``/hadith/rijal/hubs``
and ``/hadith/{collection}/{number}`` are both two segments, so the parameterised
route swallowed every rijal path and returned 404 for all of them — a collision
that only shows up at request time and looks exactly like a missing feature.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from qra.analytics import rijal
from qra.api.deps import needs
from qra.db import get_session

router = APIRouter(prefix="/rijal", tags=["rijal"])


@router.get("")
def rijal_summary(session: Session = Depends(get_session)) -> dict:
    """Size of the transmission graph, and whether it has been built."""
    return rijal.summary(session)


@router.get("/hubs")
def rijal_hubs(limit: int = 25, session: Session = Depends(get_session)) -> dict:
    """The names the corpus flows through, by weighted degree."""
    return rijal.hubs(session, limit=min(limit, 100))


@router.get("/conflation")
def rijal_conflation(
    limit: int = 25, min_narrations: int = 20, session: Session = Depends(get_session)
) -> dict:
    """Names that are probably several men.

    Read this before treating any node in the graph as a person. It is the
    central weakness of name-based isnad analysis and almost no study reports it.
    """
    return rijal.conflation_report(
        session, limit=min(limit, 100), min_narrations=max(min_narrations, 2)
    )


@router.get("/search")
def rijal_search(
    q: str, limit: int = 20, session: Session = Depends(get_session)
) -> dict:
    """Find a narrator by name.

    Declared before /narrator/{narrator_id} for readability only — they do not
    collide, since one is /search and the other is two segments. The rijal
    router exists at all because a collision of exactly that kind sent every
    path here to 404.
    """
    try:
        return rijal.search(session, q, limit=limit)
    except rijal.RijalError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/common-link")
def rijal_common_link(
    hadith_ids: list[int] = Body(..., embed=True),
    session: Session = Depends(get_session),
) -> dict:
    """The narrator a bundle of parallel chains converges on, tested.

    POST rather than GET: a bundle is an arbitrary list of ids, and a URL is the
    wrong place for one. The response always carries its null model — a common
    link that random bundles of the same shape reproduce is a description of
    this bundle, not evidence about it.
    """
    if len(hadith_ids) > 200:
        raise HTTPException(422, "at most 200 narrations per bundle")
    try:
        return rijal.common_link(session, hadith_ids)
    except rijal.RijalError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/narrator/{narrator_id}")
def rijal_narrator(narrator_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return rijal.narrator(session, narrator_id)
    except rijal.RijalError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/gradings")
def record_narrator_grading(
    narrator_id: int = Body(...),
    grade: str = Body(...),
    critic: str = Body(...),
    source_work: str = Body(...),
    reasoning: str = Body(""),
    notes: str | None = Body(None),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Record one critic's verdict on a narrator. The critic is not optional."""
    try:
        return rijal.record_grading(
            session,
            narrator_id,
            grade=grade,
            critic=critic,
            source_work=source_work,
            reasoning=reasoning,
            notes=notes,
        )
    except rijal.RijalError as exc:
        raise HTTPException(422, str(exc)) from exc


