"""Cross-run memory.

Every route here is tenant-scoped through the principal, and every row comes
back flagged ``citable: false``. A client that renders these as sources is
misusing them: a memory records that a conclusion was reached, and the finding
it points at is where the evidence for it lives.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from qra.agents import memory as mem
from qra.api.deps import principal_or_local
from qra.db import get_session
from qra.security.auth import Principal

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("")
def recall(
    q: str = Query("", description="a question; keys are derived from it"),
    key: list[str] | None = Query(None, description="explicit memory keys"),
    kind: str | None = Query(None, description="result | dead_end | caveat"),
    limit: int = 10,
    include_stale: bool = False,
    session: Session = Depends(get_session),
    principal: Principal = Depends(principal_or_local),
) -> dict:
    keys = list(key) if key else mem.keys_for(q)
    try:
        rows = mem.recall(
            session,
            keys,
            kinds=(kind,) if kind else None,
            limit=min(limit, 100),
            principal=principal,
            include_stale=include_stale,
        )
    except mem.MemoryError_ as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "keys": keys,
        "count": len(rows),
        "memories": rows,
        "note": "memory is a pointer to a finding, not a source. Nothing here is citable.",
    }


@router.post("")
def remember(
    kind: str = Body(...),
    key: str = Body(...),
    statement: str = Body(...),
    detail: dict | None = Body(None),
    finding_id: int | None = Body(None),
    run_id: str | None = Body(None),
    evidence_level: str = Body("L4"),
    session: Session = Depends(get_session),
    principal: Principal = Depends(principal_or_local),
) -> dict:
    try:
        return mem.remember(
            session,
            kind=kind,
            key=key,
            statement=statement,
            detail=detail,
            finding_id=finding_id,
            run_id=run_id,
            evidence_level=evidence_level,
            principal=principal,
        )
    except mem.MemoryError_ as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{memory_id}/forget")
def forget(
    memory_id: int,
    reason: str = Body(..., embed=True),
    session: Session = Depends(get_session),
    principal: Principal = Depends(principal_or_local),
) -> dict:
    try:
        return mem.forget(session, memory_id, reason=reason, principal=principal)
    except mem.MemoryError_ as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/stats")
def stats(
    session: Session = Depends(get_session),
    principal: Principal = Depends(principal_or_local),
) -> dict:
    return mem.stats(session, principal=principal)
