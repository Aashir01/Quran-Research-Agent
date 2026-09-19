"""Study series and the trainer (Track F)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from qra.api.deps import principal_or_local
from qra.db import get_session
from qra.security.auth import Principal
from qra.study import series as series_mod
from qra.study import trainer as trainer_mod

router = APIRouter(prefix="/study", tags=["study"])


# --- series ----------------------------------------------------------------


@router.get("/series")
def listing(published_only: bool = False, session: Session = Depends(get_session)) -> dict:
    return series_mod.series_listing(session, published_only=published_only)


@router.post("/series")
def create(
    title: str = Body(...),
    items: list[dict] = Body(...),
    description: str = Body(""),
    kind: str = Body("reading"),
    published: bool = Body(False),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    """Author a series. Every item is resolved against the corpus first — a
    broken step found by a learner mid-sequence is a broken sequence."""
    try:
        return series_mod.create_series(
            session,
            title=title,
            items=items,
            description=description,
            kind=kind,
            author_id=principal.user_id,
            org_id=principal.org_id,
            published=published,
        )
    except series_mod.SeriesError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/series/{series_id}")
def one(
    series_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return series_mod.get_series(session, series_id, user_id=principal.user_id)
    except series_mod.SeriesError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/series/{series_id}/done/{position}")
def done(
    series_id: int,
    position: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return series_mod.mark_done(session, series_id, principal.user_id, position)
    except series_mod.SeriesError as exc:
        raise HTTPException(404, str(exc)) from exc


# --- trainer ---------------------------------------------------------------


@router.get("/trainer")
def trainer_kinds(session: Session = Depends(get_session)) -> dict:
    """What can be drilled, and what cannot until a lexicon is loaded."""
    return trainer_mod.available_kinds(session)


@router.get("/trainer/due")
def due(
    limit: int = 20,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    """Cards due now. Prompts and answers are rendered from the corpus."""
    return trainer_mod.due(session, principal.user_id, limit=min(limit, 100))


@router.post("/trainer/cards")
def add_card(
    kind: str = Body(...),
    subject: str = Body(...),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return trainer_mod.add_card(session, principal.user_id, kind=kind, subject=subject)
    except trainer_mod.TrainerError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/trainer/cards/{card_id}/grade")
def grade(
    card_id: int,
    value: int = Body(..., embed=True),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return trainer_mod.grade(session, card_id, value)
    except trainer_mod.TrainerError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/trainer/stats")
def stats(
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    """Has the scheduler been right? The only honest self-assessment it has."""
    return trainer_mod.review_stats(session, principal.user_id)


@router.get("/trainer/suggestions")
def suggestions(
    kind: str = "root_location", count: int = 10, session: Session = Depends(get_session)
) -> dict:
    try:
        return {"suggestions": trainer_mod.suggest_cards(session, kind=kind, count=min(count, 50))}
    except trainer_mod.TrainerError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/trainer/from-series/{series_id}")
def from_series(
    series_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    return trainer_mod.seed_from_series(session, principal.user_id, series_id)
