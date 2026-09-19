"""The claim registry (Track G).

A Finding is what a run produced; a Claim is an assertion the team stands
behind. Status here is a projection of an append-only history rather than a
value someone set, so every route that changes a claim requires a reason and
records who gave it.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from qra.api.deps import needs, principal_or_local
from qra.db import get_session
from qra.registry import service
from qra.registry.service import ClaimError
from qra.security.auth import Principal

router = APIRouter(prefix="/claims", tags=["claims"])


def _handle(exc: ClaimError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("")
def listing(
    status: str | None = None,
    evidence_level: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """Every claim, by status and evidence level."""
    return service.listing(
        session, status=status, evidence_level=evidence_level, limit=min(limit, 200)
    )


@router.post("")
def propose(
    statement: str = Body(...),
    evidence_level: str = Body("L4"),
    reason: str = Body(""),
    language: str = Body("en"),
    ayah_ids: list[int] | None = Body(None),
    root_ids: list[int] | None = Body(None),
    citations: list[dict] | None = Body(None),
    finding_id: int | None = Body(None),
    hypothesis_id: int | None = Body(None),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    """Enter a claim, at the level its evidence supports.

    L0 and L1 assert what the sources say and are refused without a citation.
    """
    try:
        return service.propose(
            session,
            principal,
            statement=statement,
            evidence_level=evidence_level,
            reason=reason,
            language=language,
            ayah_ids=ayah_ids,
            root_ids=root_ids,
            citations=citations,
            finding_id=finding_id,
            hypothesis_id=hypothesis_id,
        )
    except ClaimError as exc:
        raise _handle(exc) from exc


@router.get("/{claim_id}")
def one_claim(claim_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return service.claim(session, claim_id)
    except ClaimError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{claim_id}/history")
def claim_history(claim_id: int, session: Session = Depends(get_session)) -> list[dict]:
    """Who changed this claim, when, and why. The status is derived from it."""
    return service.history(session, claim_id)


@router.post("/{claim_id}/status")
def set_status(
    claim_id: int,
    status: str = Body(...),
    reason: str = Body(...),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    """Move a claim. Promotion to an asserting status needs a reviewer who is
    not the author."""
    try:
        return service.set_status(session, principal, claim_id, status=status, reason=reason)
    except ClaimError as exc:
        raise _handle(exc) from exc


@router.post("/{claim_id}/objections")
def raise_objection(
    claim_id: int,
    objection: str = Body(...),
    survives_if: str = Body(""),
    kind: str = Body("human"),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    """Record an objection beside the claim.

    An asserting claim that draws an unanswered objection is moved to
    `contested` — leaving it 'supported' would state more confidence than the
    registry has.
    """
    try:
        return service.raise_objection(
            session, principal, claim_id, objection=objection, survives_if=survives_if, kind=kind
        )
    except ClaimError as exc:
        raise _handle(exc) from exc


@router.post("/{claim_id}/evidence")
def add_evidence(
    claim_id: int,
    citations: list[dict] = Body(...),
    reason: str = Body(...),
    ayah_ids: list[int] | None = Body(None),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.add_evidence(
            session, principal, claim_id, citations=citations, reason=reason, ayah_ids=ayah_ids
        )
    except ClaimError as exc:
        raise _handle(exc) from exc


@router.post("/{claim_id}/supersede")
def supersede(
    claim_id: int,
    replacement_id: int = Body(...),
    reason: str = Body(...),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Point a claim at the one that replaced it. Nothing is deleted — a claim
    once believed and then dropped is what stops it being rediscovered."""
    try:
        return service.supersede(
            session, principal, claim_id, replacement_id=replacement_id, reason=reason
        )
    except ClaimError as exc:
        raise _handle(exc) from exc
