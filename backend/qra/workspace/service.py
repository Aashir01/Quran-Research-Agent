"""Researcher workspace: anchored notes, hypothesis history, team layer.

Two rules shape this module:

* **Every note is anchored to corpus ids** — ayah, root or concept. Backlinks
  are therefore free and exact: the graph a researcher navigates is the Qur'an
  itself, not a folder tree they have to maintain.
* **Every rendered claim is tagged** ``retrieved`` / ``system_suggested`` /
  ``own_note``. The tag is a column with a check constraint, not a UI
  convention, so it cannot be lost in transit.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.hypothesis import HypothesisSpec, compile_hypothesis, run_hypothesis
from qra.models import (
    Ayah,
    Concept,
    Finding,
    Hypothesis,
    HypothesisRun,
    Note,
    NoteAnchor,
    Root,
    TopicRegistration,
    User,
)

PROVENANCE = ("retrieved", "system_suggested", "own_note")

# [[2:255]] in a note body becomes an anchor automatically.
ANCHOR_RE = re.compile(r"\[\[(\d+):(\d+)\]\]")
ROOT_ANCHOR_RE = re.compile(r"\[\[root:([^\]]+)\]\]")


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def create_note(
    session: Session,
    *,
    title: str,
    body: str,
    author_id: int | None = None,
    language: str = "en",
    provenance: str = "own_note",
    tags: list[str] | None = None,
    ayah_refs: list[str] | None = None,
    root_refs: list[str] | None = None,
    visibility: str = "private",
    org_id: int | None = None,
) -> dict:
    if provenance not in PROVENANCE:
        raise ValueError(f"provenance must be one of {PROVENANCE}")

    note = Note(
        title=title,
        body=body,
        author_id=author_id,
        org_id=org_id,
        language=language,
        provenance=provenance,
        tags=tags or [],
        visibility=visibility,
    )
    session.add(note)
    session.flush()

    refs = set(ayah_refs or [])
    refs |= {f"{s}:{a}" for s, a in ANCHOR_RE.findall(body)}
    for ref in refs:
        surah, _, ayah_num = ref.partition(":")
        ayah = session.scalar(
            select(Ayah).where(Ayah.surah_id == int(surah), Ayah.ayah_num == int(ayah_num))
        )
        if ayah is None:
            continue
        session.add(NoteAnchor(note_id=note.id, ayah_id=ayah.id, quote=ayah.text_uthmani[:200]))

    roots = set(root_refs or []) | set(ROOT_ANCHOR_RE.findall(body))
    for value in roots:
        from qra.arabic import normalise_root

        row = session.scalar(select(Root).where(Root.root == normalise_root(value)))
        if row is not None:
            session.add(NoteAnchor(note_id=note.id, root_id=row.id))

    session.commit()
    return get_note(session, note.id)


def get_note(session: Session, note_id: int, *, principal=None) -> dict:
    note = session.get(Note, note_id)
    if note is None:
        return {}
    if principal is not None and not _may_read(principal, note):
        # Indistinguishable from "not found": a 403 here would confirm the note
        # exists to someone with no right to know that.
        return {}
    anchors = session.scalars(select(NoteAnchor).where(NoteAnchor.note_id == note_id)).all()
    return {
        "id": note.id,
        "title": note.title,
        "body": note.body,
        "language": note.language,
        "provenance": note.provenance,
        "tags": note.tags,
        "visibility": note.visibility,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
        "anchors": [
            {
                "ayah_id": a.ayah_id,
                "ref": _ayah_ref(session, a.ayah_id) if a.ayah_id else None,
                "root_id": a.root_id,
                "quote": a.quote,
            }
            for a in anchors
        ],
    }


def _ayah_ref(session: Session, ayah_id: int | None) -> str | None:
    if not ayah_id:
        return None
    ayah = session.get(Ayah, ayah_id)
    return f"{ayah.surah_id}:{ayah.ayah_num}" if ayah else None


def notes_for_ayah(session: Session, surah: int, ayah_num: int) -> list[dict]:
    """Backlinks: every note anchored to this ayah."""
    ayah = session.scalar(select(Ayah).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah_num))
    if ayah is None:
        return []
    note_ids = session.scalars(
        select(NoteAnchor.note_id).where(NoteAnchor.ayah_id == ayah.id)
    ).all()
    return [get_note(session, nid) for nid in dict.fromkeys(note_ids)]


def notes_for_root(session: Session, root: str) -> list[dict]:
    from qra.arabic import normalise_root

    row = session.scalar(select(Root).where(Root.root == normalise_root(root)))
    if row is None:
        return []
    note_ids = session.scalars(select(NoteAnchor.note_id).where(NoteAnchor.root_id == row.id)).all()
    return [get_note(session, nid) for nid in dict.fromkeys(note_ids)]


def _may_read(principal, row) -> bool:
    """Own rows always; org rows when they are shared; nothing else."""
    if getattr(row, "author_id", None) == principal.user_id:
        return True
    if getattr(row, "visibility", "private") == "private":
        return False
    return getattr(row, "org_id", None) == principal.org_id


def _may_write(principal, row) -> bool:
    return principal.owns(row)


def list_notes(
    session: Session,
    *,
    principal=None,
    author_id: int | None = None,
    mine_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    stmt = select(Note).order_by(Note.updated_at.desc()).limit(limit)
    if author_id:
        stmt = stmt.where(Note.author_id == author_id)
    rows = session.scalars(stmt).all()
    if principal is not None:
        if mine_only:
            rows = [n for n in rows if n.author_id == principal.user_id]
        else:
            rows = [n for n in rows if _may_read(principal, n)]
    return [get_note(session, n.id) for n in rows]


def update_note(session: Session, note_id: int, *, principal=None, **fields) -> dict:
    note = session.get(Note, note_id)
    if note is None:
        return {}
    if principal is not None and not _may_write(principal, note):
        raise PermissionError("you can only edit your own notes")
    for key in ("title", "body", "language", "tags", "visibility", "provenance"):
        if key in fields and fields[key] is not None:
            if key == "provenance" and fields[key] not in PROVENANCE:
                raise ValueError(f"provenance must be one of {PROVENANCE}")
            setattr(note, key, fields[key])
    session.commit()
    return get_note(session, note_id)


def delete_note(session: Session, note_id: int, *, principal=None) -> bool:
    note = session.get(Note, note_id)
    if note is None:
        return False
    if principal is not None and not _may_write(principal, note):
        raise PermissionError("you can only delete your own notes")
    session.delete(note)
    session.commit()
    return True


# ---------------------------------------------------------------------------
# Hypotheses — believed -> tested -> abandoned, with the reason recorded
# ---------------------------------------------------------------------------

STATUSES = ("believed", "testing", "tested", "supported", "refuted", "abandoned")


def create_hypothesis(
    session: Session,
    *,
    title: str,
    statement: str,
    language: str = "ur",
    author_id: int | None = None,
    org_id: int | None = None,
    compile_now: bool = True,
) -> dict:
    compiled: dict = {}
    if compile_now:
        try:
            compiled = compile_hypothesis(session, statement, language=language).to_dict()
        except ValueError as exc:
            compiled = {"error": str(exc)}
    row = Hypothesis(
        title=title,
        statement=statement,
        language=language,
        author_id=author_id,
        org_id=org_id,
        compiled_query=compiled,
        status="believed",
        version=1,
    )
    session.add(row)
    session.commit()
    return serialise_hypothesis(session, row)


def revise_hypothesis(
    session: Session, hypothesis_id: int, *, statement: str, reason: str | None = None
) -> dict:
    """A revision is a new version, not an edit — the history is the point."""
    parent = session.get(Hypothesis, hypothesis_id)
    if parent is None:
        return {}
    child = Hypothesis(
        title=parent.title,
        statement=statement,
        language=parent.language,
        author_id=parent.author_id,
        compiled_query=compile_hypothesis(session, statement, language=parent.language).to_dict(),
        status="believed",
        version=parent.version + 1,
        parent_id=parent.id,
    )
    parent.abandoned_reason = reason or parent.abandoned_reason
    session.add(child)
    session.commit()
    return serialise_hypothesis(session, child)


def set_hypothesis_status(
    session: Session, hypothesis_id: int, status: str, *, reason: str | None = None
) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    row = session.get(Hypothesis, hypothesis_id)
    if row is None:
        return {}
    if status == "abandoned" and not reason:
        # Abandoning without a recorded reason is how a team loses its memory.
        raise ValueError("abandoning a hypothesis requires a reason")
    row.status = status
    if reason:
        row.abandoned_reason = reason
    session.commit()
    return serialise_hypothesis(session, row)


def test_hypothesis(session: Session, hypothesis_id: int, *, sample: int = 50) -> dict:
    row = session.get(Hypothesis, hypothesis_id)
    if row is None:
        return {}
    spec = (
        HypothesisSpec.from_dict(row.compiled_query)
        if row.compiled_query and "claim_type" in row.compiled_query
        else compile_hypothesis(session, row.statement, language=row.language)
    )
    result = run_hypothesis(session, spec, sample=sample)
    run = HypothesisRun(
        hypothesis_id=row.id,
        compiled_query=spec.to_dict(),
        # The complete sets, not the display sample — a stored run is the audit
        # trail, and a truncated one would understate the counter-examples.
        supporting=result.supporting_ids,
        violating=result.violating_ids,
        coverage=result.coverage,
        statistics=result.statistics,
        verdict=result.verdict,
    )
    row.status = {
        "refuted": "refuted",
        "supported": "supported",
        "supported_with_caveats": "tested",
        "not_supported": "tested",
    }.get(result.verdict, "tested")
    row.compiled_query = spec.to_dict()
    session.add(run)
    session.commit()
    return {"hypothesis": serialise_hypothesis(session, row), "result": result.to_dict()}


def serialise_hypothesis(session: Session, row: Hypothesis) -> dict:
    runs = session.scalars(
        select(HypothesisRun)
        .where(HypothesisRun.hypothesis_id == row.id)
        .order_by(HypothesisRun.created_at.desc())
    ).all()
    return {
        "id": row.id,
        "title": row.title,
        "statement": row.statement,
        "language": row.language,
        "status": row.status,
        "version": row.version,
        "parent_id": row.parent_id,
        "abandoned_reason": row.abandoned_reason,
        "compiled_query": row.compiled_query,
        "created_at": row.created_at.isoformat(),
        "runs": [
            {
                "id": r.id,
                "verdict": r.verdict,
                "coverage": r.coverage,
                "violating_count": len(r.violating),
                "supporting_count": len(r.supporting),
                "statistics": r.statistics,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ],
    }


def list_hypotheses(
    session: Session, *, principal=None, author_id: int | None = None, mine_only: bool = False
) -> list[dict]:
    stmt = select(Hypothesis).order_by(Hypothesis.updated_at.desc())
    if author_id:
        stmt = stmt.where(Hypothesis.author_id == author_id)
    rows = session.scalars(stmt).all()
    if principal is not None:
        if mine_only:
            rows = [h for h in rows if h.author_id == principal.user_id]
        else:
            rows = [
                h
                for h in rows
                if h.author_id == principal.user_id or h.org_id == principal.org_id
            ]
    return [serialise_hypothesis(session, h) for h in rows]


def hypothesis_history(session: Session, hypothesis_id: int) -> list[dict]:
    """Walk the version chain from the original claim to the current one."""
    chain: list[dict] = []
    row = session.get(Hypothesis, hypothesis_id)
    while row is not None:
        chain.append(serialise_hypothesis(session, row))
        row = session.get(Hypothesis, row.parent_id) if row.parent_id else None
    return list(reversed(chain))


# ---------------------------------------------------------------------------
# Team layer: topic registry, review queue
# ---------------------------------------------------------------------------


def register_topic(
    session: Session, *, topic: str, owner_id: int | None = None, org_id: int | None = None
) -> dict:
    slug = re.sub(r"\W+", "-", topic.lower()).strip("-")[:120]
    existing = session.scalars(
        select(TopicRegistration).where(TopicRegistration.slug == slug)
    ).all()
    row = TopicRegistration(topic=topic, slug=slug, owner_id=owner_id, org_id=org_id)
    session.add(row)
    session.commit()
    return {
        "id": row.id,
        "topic": topic,
        "slug": slug,
        "already_claimed_by": [
            {"id": e.id, "owner_id": e.owner_id, "created_at": e.created_at.isoformat()}
            for e in existing
        ],
        "warning": (
            f"{len(existing)} researcher(s) already registered this topic — talk to them first."
            if existing
            else None
        ),
    }


def review_queue(session: Session, *, status: str = "submitted") -> list[dict]:
    rows = session.scalars(
        select(Finding).where(Finding.review_status == status).order_by(Finding.created_at)
    ).all()
    return [
        {
            "id": f.id,
            "question": f.question,
            "summary": f.summary[:600],
            "ayah_ids": f.ayah_ids[:20],
            "author_id": f.author_id,
            "review_status": f.review_status,
            "created_at": f.created_at.isoformat(),
        }
        for f in rows
    ]


def submit_for_review(session: Session, finding_id: int) -> dict:
    finding = session.get(Finding, finding_id)
    if finding is None:
        return {}
    finding.review_status = "submitted"
    session.commit()
    return {"id": finding.id, "review_status": finding.review_status}


def review_finding(
    session: Session,
    finding_id: int,
    *,
    reviewer_id: int,
    approve: bool,
    notes: str | None = None,
    principal=None,
) -> dict:
    """Sign-off gate: nothing becomes public without a named reviewer.

    Two separate rules, both enforced here rather than in the route: the actor
    must hold the reviewer role, and no one may sign off their own work.
    """
    finding = session.get(Finding, finding_id)
    if finding is None:
        return {}
    if principal is not None:
        principal.require("reviewer")
        if principal.user_id != reviewer_id:
            raise ValueError("reviewer_id must match the authenticated reviewer")
    if reviewer_id == finding.author_id:
        raise ValueError("a finding cannot be approved by its own author")
    finding.review_status = "approved" if approve else "changes_requested"
    finding.reviewer_id = reviewer_id
    finding.reviewed_at = datetime.now(UTC)
    finding.review_notes = notes
    session.commit()
    return {
        "id": finding.id,
        "review_status": finding.review_status,
        "reviewer_id": reviewer_id,
        "public": finding.review_status == "approved",
    }


def search_prior_work(session: Session, question: str, *, limit: int = 10) -> list[dict]:
    """"Someone already researched this in March." """
    terms = [t for t in re.split(r"\W+", question.lower()) if len(t) > 3]
    if not terms:
        return []
    pattern = "|".join(re.escape(t) for t in terms[:6])
    rows = session.scalars(
        select(Finding)
        .where(func.lower(Finding.question).op("~")(pattern))
        .order_by(Finding.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": f.id,
            "question": f.question,
            "author_id": f.author_id,
            "review_status": f.review_status,
            "created_at": f.created_at.isoformat(),
            "summary": f.summary[:400],
        }
        for f in rows
    ]


def ensure_user(session: Session, email: str, display_name: str | None = None) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=display_name or email.split("@")[0])
        session.add(user)
        session.commit()
    return user


def concept_index(session: Session) -> list[dict]:
    return [
        {"slug": c.slug, "label_en": c.label_en, "label_ur": c.label_ur, "label_ar": c.label_ar}
        for c in session.scalars(select(Concept).order_by(Concept.slug)).all()
    ]
