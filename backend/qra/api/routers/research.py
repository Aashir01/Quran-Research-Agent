"""Agent runs: start a research question, inspect the ledger, read the draft."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from qra.agents.graph import LANGGRAPH_AVAILABLE, run_research
from qra.agents.llm import status as llm_status
from qra.agents.render import render
from qra.api.deps import needs
from qra.db import get_session
from qra.jobs import enqueue, job_status
from qra.models import Finding, ResearchRun
from qra.workspace.service import review_finding, review_queue, search_prior_work, submit_for_review

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/runs")
def start_run(
    question: str = Body(..., embed=True),
    language: str = Body("en", embed=True),
    background: bool = Body(True, embed=True),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Start a multi-agent run. Long runs are queued; short ones can be inline."""
    prior = search_prior_work(session, question)
    if background:
        job = enqueue(
            "research",
            lambda s: run_research(
                s, question, language=language, author_id=principal.user_id
            ),
        )
        return {"job": job, "prior_work": prior}
    result = run_research(session, question, language=language, author_id=principal.user_id)
    return {"result": result, "prior_work": prior}


@router.get("/runs")
def list_runs(limit: int = 25, session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(
        select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "run_id": r.id,
            "question": r.question,
            "status": r.status,
            "language": r.language,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    rendered = render(session, run.output or "", strict=False)
    ledger = run.ledger or {}
    return {
        "run_id": run.id,
        "question": run.question,
        "status": run.status,
        "draft_template": run.output,
        "output": rendered.text,
        "citations": rendered.citations,
        "critic_report": ledger.get("critic_report"),
        "claims": ledger.get("claims", []),
        "disagreements": ledger.get("disagreements", []),
        "statistics": ledger.get("statistics", []),
        "open_questions": ledger.get("open_questions", []),
        "events": ledger.get("events", []),
    }


@router.get("/runs/{run_id}/ledger")
def get_ledger(run_id: str, session: Session = Depends(get_session)) -> dict:
    """The full evidence ledger — every span, claim and agent event."""
    run = session.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    return run.ledger or {}


@router.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    payload = job_status(job_id)
    if not payload:
        raise HTTPException(404, f"job {job_id} not found")
    return payload


@router.get("/findings")
def findings(status: str | None = None, limit: int = 50, session: Session = Depends(get_session)) -> list[dict]:
    stmt = select(Finding).order_by(Finding.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Finding.review_status == status)
    return [
        {
            "id": f.id,
            "question": f.question,
            "summary": f.summary[:500],
            "review_status": f.review_status,
            "run_id": f.run_id,
            "created_at": f.created_at.isoformat(),
        }
        for f in session.scalars(stmt).all()
    ]


@router.get("/prior-work")
def prior_work(q: str, session: Session = Depends(get_session)) -> list[dict]:
    """"Someone already researched this in March." """
    return search_prior_work(session, q)


@router.post("/findings/{finding_id}/submit")
def submit(finding_id: int, session: Session = Depends(get_session)) -> dict:
    payload = submit_for_review(session, finding_id)
    if not payload:
        raise HTTPException(404, f"finding {finding_id} not found")
    return payload


@router.get("/review-queue")
def queue(
    status: str = "submitted",
    principal=needs("reviewer"),
    session: Session = Depends(get_session),
) -> list[dict]:
    return review_queue(session, status=status)


@router.post("/findings/{finding_id}/review")
def review(
    finding_id: int,
    approve: bool = Body(..., embed=True),
    notes: str | None = Body(None, embed=True),
    principal=needs("reviewer"),
    session: Session = Depends(get_session),
) -> dict:
    """Reviewer role required, and never your own finding."""
    try:
        payload = review_finding(
            session,
            finding_id,
            reviewer_id=principal.user_id,
            approve=approve,
            notes=notes,
            principal=principal,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not payload:
        raise HTTPException(404, f"finding {finding_id} not found")
    return payload


@router.get("/status")
def status() -> dict:
    return {
        "llm": llm_status(),
        "orchestrator": "langgraph" if LANGGRAPH_AVAILABLE else "sequential",
        "note": (
            "Agents degrade gracefully: with no model configured they still retrieve, count, "
            "test hypotheses and verify citations. Only prose drafting changes."
        ),
    }
