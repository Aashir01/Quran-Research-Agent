"""The claim registry (Track G).

A ``Finding`` is what one run produced. A ``Claim`` is an assertion a team
stands behind, which may outlive several runs and be revised by later ones.

What decays in a research group is not the evidence — it is the memory of why a
claim was accepted, by whom, and what was said against it at the time. So this
registry is built around three rules.

**Status is a projection of a history, never a value someone set.** Every
change is an event with an actor and a reason, and the reason is non-nullable.
A status change with no reason is indistinguishable, six months later, from an
accident.

**`contested` is a status, not an absence of one.** Most registries force a
claim to be accepted or rejected, which is the shape this material does not
have: the classical literature disagrees about most things worth claiming, and
a schema that cannot represent disagreement will be made to lie about it.

**Claims are superseded, never deleted.** A withdrawn claim stays visible with
its reason attached, because the fact that something was once believed and then
dropped is exactly what stops the next researcher rediscovering it.

The registry also refuses two things outright: a claim asserted above the
evidence its citations can carry, and a status promotion that skips review.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Claim, ClaimEvent, User
from qra.security.auth import Principal

STATUSES = (
    "proposed",
    "under_review",
    "supported",
    "qualified",
    "contested",
    "refuted",
    "withdrawn",
)
LEVELS = ("L0", "L1", "L2", "L3", "L4")
LEVEL_MEANING = {
    "L0": "explicit in the text",
    "L1": "soundly transmitted",
    "L2": "scholarly consensus",
    "L3": "linguistically possible",
    "L4": "own inference",
}

# Statuses that assert the claim holds. Reaching one requires review — a claim
# cannot be promoted straight from `proposed` by the person who proposed it.
ASSERTING = frozenset({"supported", "qualified"})
SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_STATEMENT = 2000


class ClaimError(ValueError):
    """A registry rule was broken. Carries which one."""


def _slug(session: Session, statement: str) -> str:
    base = SLUG_RE.sub("-", statement.strip().lower()).strip("-")[:90] or "claim"
    candidate, suffix = base, 2
    while session.scalar(select(Claim.id).where(Claim.slug == candidate)) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _require_reason(reason: str) -> str:
    """Validate before mutating, never after.

    `_record` also checks, but by then the caller has already assigned the new
    status to the in-memory row. A caller that catches the error and keeps using
    the session leaves a dirty Claim behind, and the next commit persists a
    status change with no event under it — which is precisely the thing this
    registry exists to make impossible.
    """
    text = (reason or "").strip()
    if not text:
        raise ClaimError(
            "every change to a claim needs a reason. Six months from now, a status with "
            "no reason behind it is indistinguishable from an accident."
        )
    return text


def _record(
    session: Session,
    claim_row: Claim,
    principal: Principal,
    *,
    kind: str,
    reason: str,
    from_status: str | None = None,
    to_status: str | None = None,
    detail: dict | None = None,
) -> ClaimEvent:
    if not (reason or "").strip():
        raise ClaimError(
            "every change to a claim needs a reason. Six months from now, a status with "
            "no reason behind it is indistinguishable from an accident."
        )
    event = ClaimEvent(
        claim_id=claim_row.id,
        kind=kind,
        actor_id=principal.user_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason.strip(),
        detail=detail or {},
    )
    session.add(event)
    return event


def propose(
    session: Session,
    principal: Principal,
    *,
    statement: str,
    evidence_level: str = "L4",
    reason: str = "",
    language: str = "en",
    ayah_ids: list[int] | None = None,
    root_ids: list[int] | None = None,
    citations: list[dict] | None = None,
    finding_id: int | None = None,
    hypothesis_id: int | None = None,
) -> dict:
    """Enter a claim into the registry, at the level its evidence supports."""
    text = (statement or "").strip()
    if not text:
        raise ClaimError("a claim needs a statement")
    if len(text) > MAX_STATEMENT:
        raise ClaimError(f"a claim statement is at most {MAX_STATEMENT:,} characters")
    if evidence_level not in LEVELS:
        raise ClaimError(f"evidence_level must be one of {', '.join(LEVELS)}")

    citations = citations or []
    # L0 and L1 assert the text or its transmission says this. Without a
    # citation there is nothing for that assertion to rest on, and the level is
    # doing work the evidence cannot.
    if evidence_level in {"L0", "L1"} and not citations:
        raise ClaimError(
            f"{evidence_level} ({LEVEL_MEANING[evidence_level]}) asserts what the sources "
            "say, and no citation was given. Either cite them or claim it at L3 "
            "(linguistically possible) or L4 (own inference)."
        )

    row = Claim(
        slug=_slug(session, text),
        statement=text,
        language=language,
        author_id=principal.user_id,
        org_id=principal.org_id,
        status="proposed",
        evidence_level=evidence_level,
        ayah_ids=ayah_ids or [],
        root_ids=root_ids or [],
        citations=citations,
        objections=[],
        finding_id=finding_id,
        hypothesis_id=hypothesis_id,
    )
    session.add(row)
    session.flush()
    _record(
        session,
        row,
        principal,
        kind="proposed",
        reason=reason.strip() or "entered into the registry",
        to_status="proposed",
        detail={"evidence_level": evidence_level, "citations": len(citations)},
    )
    session.commit()
    session.refresh(row)
    return serialise(session, row)


def set_status(
    session: Session,
    principal: Principal,
    claim_id: int,
    *,
    status: str,
    reason: str,
) -> dict:
    """Move a claim, recording who moved it and why."""
    row = session.get(Claim, claim_id)
    if row is None:
        raise ClaimError(f"no claim {claim_id}")
    if status not in STATUSES:
        raise ClaimError(f"status must be one of {', '.join(STATUSES)}")
    if status == row.status:
        raise ClaimError(f"this claim is already '{status}'")
    reason = _require_reason(reason)

    # Promotion to an asserting status is a review decision, and a reviewer is
    # not the author. Without this the registry records self-approval as though
    # it were review, which is worse than having no status at all.
    if status in ASSERTING:
        if row.status == "proposed":
            raise ClaimError(
                f"a claim cannot go straight from 'proposed' to '{status}'. Move it to "
                "'under_review' first — the point of the registry is that the promotion "
                "has a reviewer behind it."
            )
        if row.author_id == principal.user_id and not principal.has_role("reviewer"):
            raise ClaimError(
                "the author of a claim cannot promote it. That is self-approval recorded "
                "as review, which is worse than no status at all."
            )

    previous = row.status
    row.status = status
    _record(
        session,
        row,
        principal,
        kind="status_changed",
        reason=reason,
        from_status=previous,
        to_status=status,
    )
    session.commit()
    session.refresh(row)
    return serialise(session, row)


def raise_objection(
    session: Session,
    principal: Principal,
    claim_id: int,
    *,
    objection: str,
    survives_if: str = "",
    kind: str = "human",
    auto_contest: bool = True,
) -> dict:
    """Record an objection against a claim, beside the claim itself.

    Objections live on the claim rather than in a separate table nobody opens.
    An asserting claim that draws one is moved to ``contested`` automatically:
    leaving it marked 'supported' while an unanswered objection sits underneath
    is the registry telling a reader something it knows to be doubtful.
    """
    row = session.get(Claim, claim_id)
    if row is None:
        raise ClaimError(f"no claim {claim_id}")
    if not (objection or "").strip():
        raise ClaimError("an objection needs its content")
    _require_reason(objection)

    entry = {
        "objection": objection.strip(),
        "survives_if": survives_if.strip(),
        "kind": kind,
        "raised_by": principal.display_name or principal.email,
        "raised_at": datetime.now(UTC).isoformat(),
        "answered": False,
    }
    row.objections = [*(row.objections or []), entry]
    _record(
        session,
        row,
        principal,
        kind="objection_raised",
        reason=objection.strip()[:500],
        detail={"survives_if": survives_if, "kind": kind},
    )

    if auto_contest and row.status in ASSERTING:
        previous = row.status
        row.status = "contested"
        _record(
            session,
            row,
            principal,
            kind="status_changed",
            reason=(
                "an unanswered objection was raised against an asserting claim; leaving it "
                f"'{previous}' would state more confidence than the registry has"
            ),
            from_status=previous,
            to_status="contested",
        )
    session.commit()
    session.refresh(row)
    return serialise(session, row)


def add_evidence(
    session: Session,
    principal: Principal,
    claim_id: int,
    *,
    citations: list[dict],
    reason: str,
    ayah_ids: list[int] | None = None,
) -> dict:
    row = session.get(Claim, claim_id)
    if row is None:
        raise ClaimError(f"no claim {claim_id}")
    if not citations:
        raise ClaimError("no citations were given")
    reason = _require_reason(reason)
    row.citations = [*(row.citations or []), *citations]
    if ayah_ids:
        row.ayah_ids = sorted({*(row.ayah_ids or []), *ayah_ids})
    _record(
        session,
        row,
        principal,
        kind="evidence_added",
        reason=reason,
        detail={"added": len(citations)},
    )
    session.commit()
    session.refresh(row)
    return serialise(session, row)


def supersede(
    session: Session,
    principal: Principal,
    claim_id: int,
    *,
    replacement_id: int,
    reason: str,
) -> dict:
    """Point a claim at the one that replaced it. Nothing is deleted."""
    row = session.get(Claim, claim_id)
    replacement = session.get(Claim, replacement_id)
    if row is None or replacement is None:
        raise ClaimError("both the claim and its replacement must exist")
    if replacement_id == claim_id:
        raise ClaimError("a claim cannot supersede itself")
    reason = _require_reason(reason)
    # Walk the chain to make sure the replacement does not lead back here.
    seen, cursor = {claim_id}, replacement
    while cursor is not None and cursor.superseded_by_id is not None:
        if cursor.superseded_by_id in seen:
            raise ClaimError(
                "that would make a cycle: the replacement is already superseded by this claim"
            )
        seen.add(cursor.id)
        cursor = session.get(Claim, cursor.superseded_by_id)

    row.superseded_by_id = replacement_id
    previous = row.status
    row.status = "withdrawn"
    _record(
        session,
        row,
        principal,
        kind="superseded",
        reason=reason,
        from_status=previous,
        to_status="withdrawn",
        detail={"superseded_by": replacement_id, "replacement_slug": replacement.slug},
    )
    session.commit()
    session.refresh(row)
    return serialise(session, row)


def claim(session: Session, claim_id: int) -> dict:
    row = session.get(Claim, claim_id)
    if row is None:
        raise ClaimError(f"no claim {claim_id}")
    return serialise(session, row, with_history=True)


def history(session: Session, claim_id: int) -> list[dict]:
    rows = session.scalars(
        select(ClaimEvent).where(ClaimEvent.claim_id == claim_id).order_by(ClaimEvent.id)
    ).all()
    names = dict(session.execute(select(User.id, User.display_name)).all())
    return [
        {
            "kind": event.kind,
            "actor": names.get(event.actor_id, "unknown"),
            "from_status": event.from_status,
            "to_status": event.to_status,
            "reason": event.reason,
            "detail": event.detail or {},
            "at": event.created_at.isoformat(),
        }
        for event in rows
    ]


def listing(
    session: Session,
    *,
    status: str | None = None,
    evidence_level: str | None = None,
    limit: int = 50,
) -> dict:
    stmt = select(Claim).order_by(Claim.updated_at.desc())
    if status:
        stmt = stmt.where(Claim.status == status)
    if evidence_level:
        stmt = stmt.where(Claim.evidence_level == evidence_level)
    rows = session.scalars(stmt.limit(limit)).all()

    by_status = dict(
        session.execute(select(Claim.status, func.count()).group_by(Claim.status)).all()
    )
    by_level = dict(
        session.execute(
            select(Claim.evidence_level, func.count()).group_by(Claim.evidence_level)
        ).all()
    )
    total = sum(by_status.values())
    return {
        "total": total,
        "by_status": by_status,
        "by_evidence_level": by_level,
        "returned": len(rows),
        "claims": [serialise(session, row) for row in rows],
        "levels": LEVEL_MEANING,
        "note": (
            "`contested` is a status here, not a failure to reach one. The classical "
            "literature disagrees about most things worth claiming, and a registry that "
            "could not say so would be made to lie about it."
            if total
            else "The registry is empty. Claims are entered deliberately; nothing is "
            "promoted into it automatically from a run."
        ),
    }


def serialise(session: Session, row: Claim, *, with_history: bool = False) -> dict:
    author = session.get(User, row.author_id)
    objections = row.objections or []
    unanswered = [o for o in objections if not o.get("answered")]
    payload = {
        "id": row.id,
        "slug": row.slug,
        "statement": row.statement,
        "language": row.language,
        "author": author.display_name if author else "unknown",
        "status": row.status,
        "evidence_level": row.evidence_level,
        "evidence_level_meaning": LEVEL_MEANING.get(row.evidence_level, ""),
        "citations": row.citations or [],
        "ayah_ids": row.ayah_ids or [],
        "objections": objections,
        "unanswered_objections": len(unanswered),
        "superseded_by": row.superseded_by_id,
        "finding_id": row.finding_id,
        "hypothesis_id": row.hypothesis_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        # The status is a projection of the history, so the history is offered
        # beside it rather than behind a second request nobody makes.
        "status_note": (
            f"'{row.status}' is the result of {len(history(session, row.id))} recorded "
            "events, each with an actor and a reason."
        ),
    }
    if with_history:
        payload["history"] = history(session, row.id)
    return payload
