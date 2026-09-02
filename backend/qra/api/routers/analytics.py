"""Pattern engine endpoints.

Long sweeps (``/analytics/makki-madani``, hypothesis sweeps over the whole
corpus) are queued as background jobs rather than served inline — see
:mod:`qra.jobs`.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from qra.analytics import conditionals as conditionals_mod
from qra.analytics import cooccurrence as cooccurrence_mod
from qra.analytics import distribution as distribution_mod
from qra.analytics import mutashabihat as mutashabihat_mod
from qra.analytics import narrative as narrative_mod
from qra.analytics import transfer as transfer_mod
from qra.analytics.hypothesis import (
    compile_hypothesis,
    guard_notes,
    run_hypothesis,
    sample_hypotheses,
)
from qra.db import get_session
from qra.jobs import enqueue, job_status

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/profile")
def profile(session: Session = Depends(get_session)) -> dict:
    return distribution_mod.corpus_profile(session)


@router.get("/distribution/{root}")
def distribution(root: str, session: Session = Depends(get_session)) -> dict:
    payload = distribution_mod.root_distribution(session, root)
    if not payload.get("found"):
        raise HTTPException(404, f"root {root} not found")
    return payload


@router.get("/timeline")
def timeline(
    roots: list[str] = Query(...), buckets: int = 12, session: Session = Depends(get_session)
) -> dict:
    """Roots plotted along revelation order — where most patterns actually live."""
    return distribution_mod.revelation_timeline(session, roots, buckets=buckets)


@router.get("/cooccurrence")
def cooccurrence(
    root_a: str,
    root_b: str,
    scope: str = "ayah",
    background: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    """Association for one root pair, with the background-corpus question attached.

    Pass ``background=true`` to run the hadith comparison inline; it is a full
    scan, so by default the payload carries the offer rather than the answer.
    """
    payload = cooccurrence_mod.associate(session, root_a, root_b, scope=scope)
    if not payload.get("found"):
        raise HTTPException(404, f"roots not found: {payload.get('missing')}")
    if background:
        payload["background_check"] = transfer_mod.compare_pair(session, root_a, root_b)
    else:
        # WP-34: the question travels with the finding. A co-occurrence read
        # without it is one that may be about Arabic rather than about the Qur'an.
        payload["background_check"] = transfer_mod.offer(root_a, root_b)
    return payload


@router.get("/cluster")
def cluster(
    roots: list[str] = Query(...), scope: str = "ayah", session: Session = Depends(get_session)
) -> dict:
    return cooccurrence_mod.cluster_map(session, roots, scope=scope)


@router.post("/makki-madani")
def makki_madani_sweep(
    min_occurrences: int = 20, session: Session = Depends(get_session)
) -> dict:
    """A sweep over every root — queued, because it tests hundreds of hypotheses."""
    return enqueue(
        "makki_madani_sweep",
        lambda s: distribution_mod.makki_madani_sweep(s, min_occurrences=min_occurrences),
    )


@router.get("/conditionals")
def conditionals(
    roots: list[str] | None = Query(None),
    particle: str | None = None,
    revelation_place: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    return conditionals_mod.find_conditionals(
        session,
        roots=roots,
        particle=particle,
        revelation_place=revelation_place,
        min_confidence=min_confidence,
        limit=limit,
    )


@router.get("/conditionals/summary")
def conditionals_summary(session: Session = Depends(get_session)) -> dict:
    return conditionals_mod.particle_summary(session)


@router.get("/conditionals/patterns")
def conditional_patterns(
    min_count: int = 3, min_confidence: float = 0.5, session: Session = Depends(get_session)
) -> dict:
    return conditionals_mod.condition_consequence_patterns(
        session, min_count=min_count, min_confidence=min_confidence
    )


@router.get("/mutashabihat/clusters")
def mutashabihat_clusters(
    min_score: float = 0.75, min_size: int = 3, session: Session = Depends(get_session)
) -> dict:
    return mutashabihat_mod.clusters(session, min_score=min_score, min_size=min_size)


@router.get("/narrative/figures")
def narrative_figures(session: Session = Depends(get_session)) -> list[dict]:
    return narrative_mod.figures(session)


@router.get("/narrative/{figure}")
def narrative(figure: str, session: Session = Depends(get_session)) -> dict:
    payload = narrative_mod.narrative_diff(session, figure)
    if not payload.get("found"):
        raise HTTPException(404, payload.get("reason", f"figure {figure} not available"))
    return payload


# ---------------------------------------------------------------------------
# Hypothesis workbench
# ---------------------------------------------------------------------------


@router.post("/hypothesis/compile")
def compile_claim(
    statement: str = Body(..., embed=True),
    language: str = Body("ur", embed=True),
    use_llm: bool = Body(False, embed=True),
    session: Session = Depends(get_session),
) -> dict:
    """Show the researcher exactly what will be tested before testing it."""
    try:
        if use_llm:
            from qra.analytics.hypothesis import compile_with_llm

            spec = compile_with_llm(session, statement, language=language)
        else:
            spec = compile_hypothesis(session, statement, language=language)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return spec.to_dict()


@router.post("/hypothesis/run")
def run_claim(
    statement: str = Body(..., embed=True),
    language: str = Body("ur", embed=True),
    sample: int = Body(50, embed=True),
    session: Session = Depends(get_session),
) -> dict:
    try:
        spec = compile_hypothesis(session, statement, language=language)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = run_hypothesis(session, spec, sample=sample)
    payload = result.to_dict()
    payload["numerology_guard"] = guard_notes(session, result)
    return payload


@router.get("/hypothesis/samples")
def hypothesis_samples() -> list[dict]:
    return sample_hypotheses()


@router.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    payload = job_status(job_id)
    if not payload:
        raise HTTPException(404, f"job {job_id} not found")
    return payload
