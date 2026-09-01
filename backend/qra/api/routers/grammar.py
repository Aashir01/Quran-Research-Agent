"""Grammar search (WP-19).

Structural queries over the 130,030 analysed segments: the kind of question
that is a day's work with a concordance and one query here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from qra.analytics import grammar
from qra.db import get_session

router = APIRouter(prefix="/grammar", tags=["grammar"])


@router.get("/search")
def search(
    q: str,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> dict:
    """Run a grammar query. Exhaustive — the count is every match in the corpus.

    A bad query returns 422 with what to fix, never an empty result set: an
    empty answer to a mistyped feature is indistinguishable from an empty answer
    to a good question, and that is the difference between a tool and a trap.
    """
    try:
        return grammar.run(session, q, limit=min(limit, 200), offset=offset)
    except grammar.QueryError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/vocabulary")
def vocabulary(session: Session = Depends(get_session)) -> dict:
    """Everything the language accepts, with live counts from this corpus."""
    return grammar.vocabulary(session)


@router.get("/examples")
def examples() -> dict:
    return {
        "examples": grammar.EXAMPLES,
        "note": (
            "These double as eval fixtures: each is a question a researcher asks, "
            "written in the language, and each is checked against the corpus in CI."
        ),
    }
