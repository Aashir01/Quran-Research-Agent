"""Track D analysis engines: sandbox, cross-corpus transfer, balagha, naskh.

What these have in common is that each one is designed around a way it could be
misused. The sandbox exists because counting claims are easy to manufacture;
transfer exists because a pattern in Arabic looks exactly like a pattern in the
Qur'an; balagha reports only what the morphology can carry; naskh refuses to
record a claim without a claimant.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from qra.analytics import balagha, naskh, sandbox, transfer
from qra.api.deps import needs
from qra.db import get_session

router = APIRouter(prefix="/analysis", tags=["analysis"])


# --- WP-33 numerical sandbox ----------------------------------------------


@router.post("/sandbox/sessions")
def open_sandbox(
    title: str = Body(...),
    intent: str = Body(...),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Open a quarantined session. Intent is required *before* looking."""
    try:
        return sandbox.open_session(
            session, owner_id=principal.user_id, title=title, intent=intent
        )
    except sandbox.SandboxError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sandbox/sessions/{session_id}/tests")
def register_test(
    session_id: int,
    claim: str = Body(...),
    null_model: str = Body(...),
    spec: dict | None = Body(None),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Pre-register a claim. Nothing is counted until you run it."""
    try:
        return sandbox.register(
            session, session_id, claim=claim, null_model=null_model, spec=spec
        )
    except sandbox.SandboxError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sandbox/tests/{test_id}/run")
def run_test(
    test_id: int,
    observed: int = Body(...),
    n: int = Body(...),
    baseline_rate: float = Body(...),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Run a pre-registered test.

    The response always carries the session-wide correction alongside the
    individual result — a p-value from this endpoint never arrives alone.
    """
    try:
        return sandbox.run(
            session, test_id, observed=observed, n=n, baseline_rate=baseline_rate
        )
    except sandbox.SandboxError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/sandbox/sessions/{session_id}")
def sandbox_summary(session_id: int, session: Session = Depends(get_session)) -> dict:
    """The session. `headline` states how many hypotheses were tried and how
    many significant results chance predicts, before any individual result."""
    try:
        return sandbox.summary(session, session_id)
    except sandbox.SandboxError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/sandbox/sessions/{session_id}/close")
def close_sandbox(
    session_id: int,
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return sandbox.close(session, session_id)
    except sandbox.SandboxError as exc:
        raise HTTPException(404, str(exc)) from exc


# --- WP-34 cross-corpus transfer ------------------------------------------


@router.get("/transfer/pair")
def transfer_pair(a: str, b: str, session: Session = Depends(get_session)) -> dict:
    """Does this root pairing hold in the hadith corpus too?

    If it does, the "Qur'anic pattern" is probably a fact about Arabic.
    """
    return transfer.compare_pair(session, a, b)


@router.get("/transfer/root/{root}")
def transfer_root(root: str, session: Session = Depends(get_session)) -> dict:
    return transfer.compare_root(session, root)


# --- WP-27 balagha ---------------------------------------------------------


@router.get("/balagha/features")
def balagha_features(session: Session = Depends(get_session)) -> dict:
    """What is detected, and — as importantly — what is deliberately not."""
    return balagha.features(session)


@router.get("/balagha/iltifat")
def iltifat(
    surah: int | None = None,
    revelation_place: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> dict:
    return balagha.iltifat(
        session,
        surah=surah,
        revelation_place=revelation_place,
        limit=min(limit, 200),
        offset=offset,
    )


@router.get("/balagha/fixtures")
def balagha_fixtures(session: Session = Depends(get_session)) -> dict:
    """Run the hand-verified positive and negative cases against live data.

    The negative cases are the point: each is an ayah a segment-level detector
    flags and a correct one does not.
    """
    return balagha.check_fixtures(session)


@router.get("/balagha/iltifat/hotspots")
def iltifat_hotspots(session: Session = Depends(get_session)) -> dict:
    """Surahs where person shifts are denser than the corpus baseline.

    Raw shift counts are near-useless — most ayat contain one — so this is the
    view that makes the feature an analytic rather than a curiosity.
    """
    return balagha.hotspots(session)


# --- WP-30 naskh registry --------------------------------------------------


@router.get("/naskh/registry")
def naskh_registry(session: Session = Depends(get_session)) -> dict:
    return naskh.registry(session)


@router.get("/naskh/{surah}/{ayah}")
def naskh_for_ayah(surah: int, ayah: int, session: Session = Depends(get_session)) -> dict:
    """Claims touching this ayah. Never a status — always claims with claimants."""
    return naskh.for_ayah(session, surah, ayah)


@router.post("/naskh/claims")
def record_claim(
    abrogated_ref: str = Body(...),
    claimant: str = Body(...),
    source_work: str = Body(...),
    abrogating_ref: str | None = Body(None),
    basis: str = Body(""),
    kind: str = Body("ruling"),
    rejected_by: list[str] | None = Body(None),
    notes: str | None = Body(None),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return naskh.record(
            session,
            abrogated_ref=abrogated_ref,
            claimant=claimant,
            source_work=source_work,
            abrogating_ref=abrogating_ref,
            basis=basis,
            kind=kind,
            rejected_by=rejected_by,
            notes=notes,
        )
    except naskh.NaskhError as exc:
        raise HTTPException(422, str(exc)) from exc
