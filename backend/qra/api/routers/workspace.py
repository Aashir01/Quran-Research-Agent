"""Researcher workspace: anchored notes, hypothesis history, topic registry."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from qra.db import get_session
from qra.workspace import service

router = APIRouter(prefix="/workspace", tags=["workspace"])


# --- notes -----------------------------------------------------------------


@router.post("/notes")
def create_note(
    title: str = Body(...),
    body: str = Body(...),
    language: str = Body("en"),
    provenance: str = Body("own_note"),
    tags: list[str] | None = Body(None),
    ayah_refs: list[str] | None = Body(None),
    root_refs: list[str] | None = Body(None),
    author_id: int | None = Body(None),
    session: Session = Depends(get_session),
) -> dict:
    """Create a note. ``[[2:255]]`` and ``[[root:صبر]]`` in the body auto-anchor."""
    try:
        return service.create_note(
            session,
            title=title,
            body=body,
            language=language,
            provenance=provenance,
            tags=tags,
            ayah_refs=ayah_refs,
            root_refs=root_refs,
            author_id=author_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/notes")
def list_notes(author_id: int | None = None, session: Session = Depends(get_session)) -> list[dict]:
    return service.list_notes(session, author_id=author_id)


@router.get("/notes/{note_id}")
def get_note(note_id: int, session: Session = Depends(get_session)) -> dict:
    payload = service.get_note(session, note_id)
    if not payload:
        raise HTTPException(404, f"note {note_id} not found")
    return payload


@router.patch("/notes/{note_id}")
def update_note(note_id: int, fields: dict = Body(...), session: Session = Depends(get_session)) -> dict:
    payload = service.update_note(session, note_id, **fields)
    if not payload:
        raise HTTPException(404, f"note {note_id} not found")
    return payload


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, session: Session = Depends(get_session)) -> dict:
    return {"deleted": service.delete_note(session, note_id)}


@router.get("/backlinks/ayah/{surah}/{ayah}")
def backlinks(surah: int, ayah: int, session: Session = Depends(get_session)) -> list[dict]:
    """Every note anchored to this ayah — the Obsidian move, over the Qur'an's own graph."""
    return service.notes_for_ayah(session, surah, ayah)


@router.get("/backlinks/root/{root}")
def root_backlinks(root: str, session: Session = Depends(get_session)) -> list[dict]:
    return service.notes_for_root(session, root)


# --- hypotheses ------------------------------------------------------------


@router.post("/hypotheses")
def create_hypothesis(
    title: str = Body(...),
    statement: str = Body(...),
    language: str = Body("ur"),
    author_id: int | None = Body(None),
    session: Session = Depends(get_session),
) -> dict:
    return service.create_hypothesis(
        session, title=title, statement=statement, language=language, author_id=author_id
    )


@router.get("/hypotheses")
def list_hypotheses(author_id: int | None = None, session: Session = Depends(get_session)) -> list[dict]:
    return service.list_hypotheses(session, author_id=author_id)


@router.post("/hypotheses/{hypothesis_id}/test")
def test_hypothesis(hypothesis_id: int, sample: int = Body(50, embed=True), session: Session = Depends(get_session)) -> dict:
    payload = service.test_hypothesis(session, hypothesis_id, sample=sample)
    if not payload:
        raise HTTPException(404, f"hypothesis {hypothesis_id} not found")
    return payload


@router.post("/hypotheses/{hypothesis_id}/revise")
def revise_hypothesis(
    hypothesis_id: int,
    statement: str = Body(..., embed=True),
    reason: str | None = Body(None, embed=True),
    session: Session = Depends(get_session),
) -> dict:
    payload = service.revise_hypothesis(session, hypothesis_id, statement=statement, reason=reason)
    if not payload:
        raise HTTPException(404, f"hypothesis {hypothesis_id} not found")
    return payload


@router.post("/hypotheses/{hypothesis_id}/status")
def set_status(
    hypothesis_id: int,
    status: str = Body(..., embed=True),
    reason: str | None = Body(None, embed=True),
    session: Session = Depends(get_session),
) -> dict:
    """Abandoning requires a reason — that is enforced, not suggested."""
    try:
        payload = service.set_hypothesis_status(session, hypothesis_id, status, reason=reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not payload:
        raise HTTPException(404, f"hypothesis {hypothesis_id} not found")
    return payload


@router.get("/hypotheses/{hypothesis_id}/history")
def history(hypothesis_id: int, session: Session = Depends(get_session)) -> list[dict]:
    return service.hypothesis_history(session, hypothesis_id)


# --- team ------------------------------------------------------------------


@router.post("/topics")
def register_topic(
    topic: str = Body(..., embed=True),
    owner_id: int | None = Body(None, embed=True),
    session: Session = Depends(get_session),
) -> dict:
    """Claim a topic. Returns whoever already claimed it, so duplicate work surfaces early."""
    return service.register_topic(session, topic=topic, owner_id=owner_id)


@router.post("/users")
def ensure_user(
    email: str = Body(..., embed=True),
    display_name: str | None = Body(None, embed=True),
    session: Session = Depends(get_session),
) -> dict:
    user = service.ensure_user(session, email, display_name)
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}
