"""The public portal (Track G).

Read-only, unauthenticated, and deliberately narrow. Everything here is
published research, which means two things follow that the internal API does
not have to worry about.

**Nothing reaches this surface by default.** A finding appears only once a
reviewer has approved it; a claim appears only at `supported` or `qualified`.
Drafts, proposals and anything under review are invisible — not filtered out of
a listing, but never selected in the first place, so a new route added here
cannot accidentally widen the set.

**Nothing is published without what qualifies it.** Every claim carries its
evidence level and its unanswered objections; every finding carries its
citations. A portal that showed conclusions and left the caveats behind a login
would be the most damaging surface in the application, because it is the one
that gets screenshotted.

A contested claim is shown *as contested* rather than withheld. Withholding it
would let the portal read as a list of settled results, which is the impression
this material least supports.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.db import get_session
from qra.models import Claim, Finding, User
from qra.registry import service as registry

router = APIRouter(prefix="/portal", tags=["portal"])

# The only statuses that reach the public surface. Defined once, used by every
# route here, so widening it is a deliberate edit in one place rather than an
# omission in a new query.
PUBLIC_CLAIM_STATUSES = ("supported", "qualified", "contested")
PUBLIC_FINDING_STATUS = "approved"


def _published_claims():
    return select(Claim).where(
        Claim.status.in_(PUBLIC_CLAIM_STATUSES),
        Claim.superseded_by_id.is_(None),
    )


@router.get("")
def index(session: Session = Depends(get_session)) -> dict:
    """What this portal is, and what it deliberately does not show."""
    claims = session.scalar(
        select(func.count()).select_from(_published_claims().subquery())
    ) or 0
    findings = (
        session.scalar(
            select(func.count())
            .select_from(Finding)
            .where(Finding.review_status == PUBLIC_FINDING_STATUS)
        )
        or 0
    )
    return {
        "published_claims": claims,
        "published_findings": findings,
        "what_is_here": (
            "Research that has been through review. Claims appear at 'supported', "
            "'qualified' or 'contested'; findings appear once a reviewer has approved them."
        ),
        "what_is_not_here": (
            "Drafts, proposals, anything under review, and any claim that has been "
            "superseded. These are never selected rather than filtered out, so a route "
            "added here cannot widen the set by omission."
        ),
        "why_contested_claims_are_shown": (
            "Withholding them would let this page read as a list of settled results, "
            "which is the impression this material least supports. A contested claim is "
            "shown as contested, with the objection against it."
        ),
        "caveat": (
            "Every claim here carries its evidence level. L3 means the Arabic can bear "
            "this reading among others; L4 means it is someone's inference. Neither is a "
            "statement that the text says so."
        ),
    }


@router.get("/claims")
def claims(
    status: str | None = None,
    evidence_level: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """Published claims, with their level and their objections attached."""
    if status and status not in PUBLIC_CLAIM_STATUSES:
        raise HTTPException(
            404,
            f"'{status}' is not a published status. This portal shows "
            f"{', '.join(PUBLIC_CLAIM_STATUSES)}.",
        )
    stmt = _published_claims()
    if status:
        stmt = stmt.where(Claim.status == status)
    if evidence_level:
        stmt = stmt.where(Claim.evidence_level == evidence_level)
    rows = session.scalars(
        stmt.order_by(Claim.updated_at.desc()).limit(min(limit, 200))
    ).all()

    return {
        "count": len(rows),
        "claims": [_public_claim(session, row) for row in rows],
        "levels": registry.LEVEL_MEANING,
        "note": (
            "A claim shown here has a reviewer behind its status — the registry refuses "
            "to promote a claim its own author approved."
        ),
    }


@router.get("/claims/{slug}")
def one_claim(slug: str, session: Session = Depends(get_session)) -> dict:
    row = session.scalar(_published_claims().where(Claim.slug == slug))
    if row is None:
        # Deliberately indistinguishable from "does not exist": confirming that
        # an unpublished claim exists is itself a disclosure.
        raise HTTPException(404, "no published claim with that name")
    payload = _public_claim(session, row)
    payload["history"] = [
        event
        for event in registry.history(session, row.id)
        if event["kind"] in {"proposed", "status_changed", "objection_raised", "superseded"}
    ]
    return payload


def _public_claim(session: Session, row: Claim) -> dict:
    author = session.get(User, row.author_id)
    objections = row.objections or []
    return {
        "slug": row.slug,
        "statement": row.statement,
        "status": row.status,
        "evidence_level": row.evidence_level,
        "evidence_level_meaning": registry.LEVEL_MEANING.get(row.evidence_level, ""),
        "author": author.display_name if author else "unknown",
        "citations": row.citations or [],
        # Published with the claim, never behind it.
        "objections": [
            {"objection": o.get("objection"), "survives_if": o.get("survives_if")}
            for o in objections
        ],
        "unanswered_objections": sum(1 for o in objections if not o.get("answered")),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/findings")
def findings(limit: int = 30, session: Session = Depends(get_session)) -> dict:
    """Approved findings. Nothing under review is selected."""
    rows = session.scalars(
        select(Finding)
        .where(Finding.review_status == PUBLIC_FINDING_STATUS)
        .order_by(Finding.created_at.desc())
        .limit(min(limit, 100))
    ).all()
    return {
        "count": len(rows),
        "findings": [
            {
                "id": row.id,
                "question": row.question,
                "summary": row.summary,
                "language": row.language,
                "citations": row.citations or [],
                "ayah_ids": (row.ayah_ids or [])[:40],
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            }
            for row in rows
        ],
        "note": (
            "Each of these was approved by a reviewer. The citations travel with the "
            "summary because a conclusion without its sources is the thing this "
            "application exists not to produce."
        ),
    }
