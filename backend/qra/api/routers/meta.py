"""Health, corpus provenance and the licensing audit — served, not filed away."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra import sources
from qra.agents.llm import status as llm_status
from qra.api.deps import CurrentUser
from qra.db import get_session
from qra.models import (
    Ayah,
    ConditionalStructure,
    Edition,
    Hadith,
    IngestLog,
    Root,
    Segment,
    Surah,
    TafsirEntry,
    Translation,
    Word,
)
from qra.retrieval.semantic import status as semantic_status

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    ayat = session.scalar(select(func.count()).select_from(Ayah)) or 0
    return {
        "status": "ok" if ayat == 6236 else "corpus_incomplete",
        "ayat": ayat,
        "expected_ayat": 6236,
    }


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    return {
        "surahs": session.scalar(select(func.count()).select_from(Surah)),
        "ayat": session.scalar(select(func.count()).select_from(Ayah)),
        "words": session.scalar(select(func.count()).select_from(Word)),
        "segments": session.scalar(select(func.count()).select_from(Segment)),
        "roots": session.scalar(select(func.count()).select_from(Root)),
        "translations": session.scalar(select(func.count()).select_from(Translation)),
        "tafsir_entries": session.scalar(select(func.count()).select_from(TafsirEntry)),
        "hadith": session.scalar(select(func.count()).select_from(Hadith)),
        "conditional_structures": session.scalar(
            select(func.count()).select_from(ConditionalStructure)
        ),
    }


@router.get("/editions")
def editions(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(Edition).order_by(Edition.kind, Edition.slug)).all()
    return [
        {
            "slug": e.slug,
            "kind": e.kind,
            "language": e.language,
            "name": e.name,
            "author": e.author,
            "license": e.license,
            "license_status": e.license_status,
            "license_notes": e.license_notes,
            "source_url": e.source_url,
            "era": e.era,
            "death_year_hijri": e.death_year_hijri,
        }
        for e in rows
    ]


@router.get("/licenses")
def licenses() -> dict:
    """The licensing audit, live from the registry that gates ingest."""
    rows = sources.audit_rows()
    return {
        "shipped": [r for r in rows if r["shipped"]],
        "withheld": [r for r in rows if not r["shipped"]],
        "policy": (
            "Only editions whose licence status is public_domain or permissive can be ingested. "
            "Restricted editions are registered so the system can say why a text is missing "
            "instead of pretending it does not exist."
        ),
    }


@router.get("/provenance")
def provenance(session: Session = Depends(get_session)) -> list[dict]:
    """What was loaded, from where, with the checksum of the payload consumed."""
    rows = session.scalars(select(IngestLog).order_by(IngestLog.created_at.desc())).all()
    return [
        {
            "step": r.step,
            "source_url": r.source_url,
            "checksum": r.checksum,
            "rows": r.rows,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/ready")
def ready(session: Session = Depends(get_session)) -> dict:
    """Readiness, distinct from liveness: is the corpus actually loaded here?"""
    from qra import ops

    payload = ops.readiness(session)
    if not payload["ready"]:

        return JSONResponse(payload, status_code=503)
    return payload


@router.get("/cache")
def cache_stats(session: Session = Depends(get_session)) -> dict:
    from qra import cache

    return cache.stats(session)


@router.get("/jobs")
def jobs() -> dict:
    from qra.jobs import backend, list_jobs

    return {"backend": backend(), "jobs": list_jobs()}


@router.get("/usage")
def usage(principal=CurrentUser, session: Session = Depends(get_session)) -> dict:
    """What this principal has spent in the last 30 days (WP-05)."""
    from qra.budget import monthly_usage

    return monthly_usage(session, user_id=principal.user_id, org_id=principal.org_id)


@router.get("/traces")
def traces(run_id: str | None = None) -> dict:
    """Recent runs and their spans — available without any SaaS configured."""
    from qra.observability import RECORDER
    from qra.observability import status as trace_status

    if run_id:
        return {"run_id": run_id, "spans": RECORDER.spans(run_id)}
    return {"status": trace_status(), "runs": RECORDER.runs()}


@router.get("/capabilities")
def capabilities() -> dict:
    """What is on, what is off, and why — so the UI never has to guess."""
    return {
        "retrieval": {
            "deterministic": {"enabled": True, "exhaustive": True},
            "lexical_bm25": {"enabled": True, "exhaustive": False},
            "semantic": semantic_status(),
            "graph": {"enabled": True, "exhaustive": True},
        },
        "agents": llm_status(),
        "observability": __import__("qra.observability", fromlist=["status"]).status(),
        "hard_rules": [
            "Scripture, translations and hadith matn are rendered from the database by id.",
            "Every statistic is reported with its chance baseline.",
            "Hypothesis results list violations before supporting evidence.",
            "Findings need a reviewer other than the author before they are public.",
        ],
    }
