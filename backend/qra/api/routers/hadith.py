"""Hadith: takhrij, isnad, and grading provenance (WP-21).

The question worth asking of a narration is rarely "is this one sahih". It is
"where else is this narrated, through whom, and how did each collector grade
it" — and answering that by hand means reading six collections.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from qra.analytics import takhrij
from qra.analytics.isnad import split
from qra.db import get_session
from qra.models import Hadith

router = APIRouter(prefix="/hadith", tags=["hadith"])


def _resolve(session: Session, collection: str, number: str) -> Hadith:
    row = session.scalar(
        select(Hadith).where(Hadith.collection == collection, Hadith.number == number)
    )
    if row is None:
        raise HTTPException(404, f"{collection} {number} not found")
    return row


@router.get("/{collection}/{number}")
def get_hadith(
    collection: str, number: str, session: Session = Depends(get_session)
) -> dict:
    row = _resolve(session, collection, number)
    parsed = split(row.text_ar or "")
    return {
        "hadith_id": row.id,
        "ref": f"{row.collection} {row.number}",
        "book": row.book,
        "chapter": row.chapter,
        "text_ar": row.text_ar,
        "translation": row.text_translation,
        "translation_language": row.translation_language,
        # Grading is never omitted and never silently upgraded from unknown.
        "grading": row.grading,
        "graded_by": row.graded_by,
        "isnad": parsed.to_dict(),
    }


@router.get("/{collection}/{number}/takhrij")
def takhrij_for(
    collection: str,
    number: str,
    min_score: float = takhrij.MIN_SCORE,
    cross_collection_only: bool = False,
    limit: int = 25,
    session: Session = Depends(get_session),
) -> dict:
    """Every parallel narration, each with its own grade and grader.

    Exhaustive over the corpus — every narration carrying Arabic text was
    compared. The isnad split underneath is a heuristic, which is why results
    are banded rather than thresholded.
    """
    row = _resolve(session, collection, number)
    return takhrij.parallels_for(
        session,
        row.id,
        min_score=min_score,
        cross_collection_only=cross_collection_only,
        limit=min(limit, 100),
    )


@router.get("/{collection}/{number}/isnad")
def isnad_for(collection: str, number: str, session: Session = Depends(get_session)) -> dict:
    """The chain, segmented into narrators.

    Segmentation, not rijal identification: two narrators sharing a name are one
    node here, because the biographical data that would separate them is not in
    this corpus. Stated rather than glossed over.
    """
    row = _resolve(session, collection, number)
    parsed = split(row.text_ar or "")
    return {
        "ref": f"{row.collection} {row.number}",
        "grading": row.grading,
        "graded_by": row.graded_by,
        **parsed.to_dict(),
        "edges": [
            {"from": parsed.narrators[i], "to": parsed.narrators[i + 1]}
            for i in range(len(parsed.narrators) - 1)
        ],
        "caveat": (
            "Narrator names are segmented from the chain text, not matched against a "
            "rijal database. Identical names are treated as one narrator."
        ),
    }


@router.get("/takhrij/status")
def status() -> dict:
    return {
        "index_built": takhrij.index_ready(),
        "shingle_size": takhrij.SHINGLE_SIZE,
        "min_score": takhrij.MIN_SCORE,
        "bands": {"strong": takhrij.BAND_STRONG, "probable": takhrij.BAND_PROBABLE},
        "note": (
            "The index is built once per process from the ingested corpus. "
            "The first takhrij request after a restart pays for it."
        ),
    }


asbab_router = APIRouter(prefix="/asbab", tags=["asbab"])


@asbab_router.get("/{surah}/{ayah}")
def asbab_for_ayah(surah: int, ayah: int, session: Session = Depends(get_session)) -> dict:
    """Occasions of revelation for one ayah — every report with its grade.

    There is no code path here that returns a report without one: the grade is
    added during serialisation, not by the caller, so it cannot be forgotten.
    """
    from qra.analytics import asbab

    return asbab.for_ayah(session, surah, ayah)


@asbab_router.get("/coverage")
def asbab_coverage(session: Session = Depends(get_session)) -> dict:
    """How much of the Qur'an has a transmitted occasion, honestly stated.

    The number is low — around 3% — and that is the truth about the material,
    not a gap in the ingest. Most of the Qur'an has no transmitted occasion of
    revelation, and a tool implying otherwise would be inventing history.
    """
    from qra.analytics import asbab

    return asbab.coverage(session)
