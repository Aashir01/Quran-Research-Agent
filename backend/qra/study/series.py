"""Study series (Track F).

An ordered curriculum over the corpus. A series is an **editorial** object in
the same way the life domains are: deciding that the conditional structures
come before the oath forms is a teaching judgement, not a fact about the text,
and ``provenance`` says so on every row.

Items point at corpus objects and never carry their text. A series that stored
the verse would be a series that could disagree with the corpus, which is the
one thing a teaching sequence must not be able to do — a learner has no way to
notice.

Three series ship, built from what the corpus can already answer exhaustively.
They are starting points, not a syllabus: the interesting ones are the ones a
teacher writes.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Ayah, Concept, Root, SeriesItem, SeriesProgress, StudySeries

ITEM_KINDS = ("ayah_range", "root", "concept", "grammar_query")
SERIES_KINDS = ("reading", "morphology", "thematic")
SLUG_RE = re.compile(r"[^a-z0-9]+")


class SeriesError(ValueError):
    pass


def _slug(session: Session, title: str) -> str:
    base = SLUG_RE.sub("-", title.strip().lower()).strip("-")[:80] or "series"
    candidate, suffix = base, 2
    while session.scalar(select(StudySeries.id).where(StudySeries.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _validate(session: Session, kind: str, target: str) -> None:
    """Refuse an item that points at nothing.

    Checked at authoring time rather than at read time, because a broken step
    discovered by a learner mid-sequence is a broken sequence.
    """
    if kind not in ITEM_KINDS:
        raise SeriesError(f"item kind must be one of {', '.join(ITEM_KINDS)}")

    if kind == "ayah_range":
        first = target.split("-")[0]
        try:
            surah, ayah = (int(p) for p in first.split(":", 1))
        except ValueError as exc:
            raise SeriesError(f"'{target}' is not a reference like 2:255 or 2:255-2:257") from exc
        if not session.scalar(
            select(Ayah.id).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
        ):
            raise SeriesError(f"{first} is not an ayah in this corpus")
    elif kind == "root":
        if not session.scalar(select(Root.id).where(Root.root_display == target)):
            raise SeriesError(f"'{target}' is not a root in this corpus")
    elif kind == "concept":
        if not session.scalar(select(Concept.id).where(Concept.slug == target)):
            raise SeriesError(f"'{target}' is not a concept slug")
    elif kind == "grammar_query":
        from qra.analytics.grammar import QueryError, parse

        try:
            parse(target)
        except QueryError as exc:
            raise SeriesError(f"'{target}' is not a valid grammar query: {exc}") from exc


def create_series(
    session: Session,
    *,
    title: str,
    items: list[dict],
    description: str = "",
    kind: str = "reading",
    author_id: int | None = None,
    org_id: int | None = None,
    published: bool = False,
) -> dict:
    if not (title or "").strip():
        raise SeriesError("a series needs a title")
    if kind not in SERIES_KINDS:
        raise SeriesError(f"kind must be one of {', '.join(SERIES_KINDS)}")
    if not items:
        raise SeriesError("a series with no items teaches nothing")

    row = StudySeries(
        slug=_slug(session, title),
        title=title.strip(),
        description=description.strip(),
        kind=kind,
        author_id=author_id,
        org_id=org_id,
        published=published,
        provenance="curated",
    )
    session.add(row)
    session.flush()

    for position, item in enumerate(items, start=1):
        item_kind = item.get("kind", "ayah_range")
        target = (item.get("target") or "").strip()
        _validate(session, item_kind, target)
        session.add(
            SeriesItem(
                series_id=row.id,
                position=position,
                kind=item_kind,
                target=target,
                note=(item.get("note") or "").strip(),
            )
        )
    session.commit()
    session.refresh(row)
    return get_series(session, row.id)


def get_series(session: Session, series_id: int, *, user_id: int | None = None) -> dict:
    row = session.get(StudySeries, series_id)
    if row is None:
        raise SeriesError(f"no series {series_id}")
    items = session.scalars(
        select(SeriesItem).where(SeriesItem.series_id == row.id).order_by(SeriesItem.position)
    ).all()
    done: set[int] = set()
    if user_id is not None:
        done = set(
            session.scalars(
                select(SeriesProgress.position).where(
                    SeriesProgress.series_id == row.id, SeriesProgress.user_id == user_id
                )
            ).all()
        )
    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "description": row.description,
        "kind": row.kind,
        "published": row.published,
        "provenance": row.provenance,
        "editorial": (
            "The order is a teaching judgement, not a fact about the text. Items point at "
            "corpus objects and carry no text of their own, so a series cannot drift from "
            "what it claims to teach."
        ),
        "items": [
            {
                "position": item.position,
                "kind": item.kind,
                "target": item.target,
                "note": item.note,
                "done": item.position in done,
            }
            for item in items
        ],
        "length": len(items),
        "completed": len(done),
    }


def mark_done(session: Session, series_id: int, user_id: int, position: int) -> dict:
    row = session.get(StudySeries, series_id)
    if row is None:
        raise SeriesError(f"no series {series_id}")
    if not session.scalar(
        select(SeriesItem.id).where(
            SeriesItem.series_id == series_id, SeriesItem.position == position
        )
    ):
        raise SeriesError(f"series {series_id} has no step {position}")
    existing = session.scalar(
        select(SeriesProgress).where(
            SeriesProgress.series_id == series_id,
            SeriesProgress.user_id == user_id,
            SeriesProgress.position == position,
        )
    )
    if existing is None:
        session.add(
            SeriesProgress(series_id=series_id, user_id=user_id, position=position)
        )
        session.commit()
    return get_series(session, series_id, user_id=user_id)


def series_listing(session: Session, *, published_only: bool = False) -> dict:
    stmt = select(StudySeries).order_by(StudySeries.created_at.desc())
    if published_only:
        stmt = stmt.where(StudySeries.published.is_(True))
    rows = session.scalars(stmt).all()
    counts = dict(
        session.execute(
            select(SeriesItem.series_id, func.count()).group_by(SeriesItem.series_id)
        ).all()
    )
    return {
        "count": len(rows),
        "series": [
            {
                "id": r.id,
                "slug": r.slug,
                "title": r.title,
                "kind": r.kind,
                "published": r.published,
                "steps": counts.get(r.id, 0),
            }
            for r in rows
        ],
        "note": (
            "Series are curated. The ones that ship are starting points built from what "
            "the corpus can answer exhaustively; the interesting ones are the ones a "
            "teacher writes."
            if rows
            else "No series yet."
        ),
    }


# ---------------------------------------------------------------------------
# The series that ship
# ---------------------------------------------------------------------------

STARTERS = (
    {
        "title": "The short Makki surahs, in revelation order",
        "kind": "reading",
        "description": (
            "The earliest material, shortest first. Revelation order follows the Egyptian "
            "standard, which is a scholarly reconstruction and disputed at the margins."
        ),
        "items": [
            {"kind": "ayah_range", "target": f"{surah}:1", "note": f"surah {surah}"}
            for surah in (96, 68, 73, 74, 1, 111, 81, 87, 92, 89)
        ],
    },
    {
        "title": "The twenty commonest roots",
        "kind": "morphology",
        "description": (
            "Ranked by occurrence in the morphology, not by importance — frequency is a "
            "fact about the text and importance is a judgement."
        ),
        "items": [],  # filled from the corpus at seed time
    },
    {
        "title": "Conditional structure in the Qur'an",
        "kind": "thematic",
        "description": (
            "The 'if X then Y' constructions, which is where the text states rules about "
            "consequence. Each step is a grammar query you can run and extend."
        ),
        "items": [
            {"kind": "grammar_query", "target": "V:PERF", "note": "perfect verbs — the usual protasis"},
            {"kind": "grammar_query", "target": "V:IMPF:JUS", "note": "jussive — negation and prohibition"},
            {"kind": "concept", "target": "taqwa", "note": "a concept the conditionals cluster around"},
            {"kind": "concept", "target": "amal", "note": "deeds, the commonest consequence term"},
        ],
    },
)


def seed_starters(session: Session) -> dict:
    """Load the shipped series. Idempotent."""
    created = []
    for spec in STARTERS:
        if session.scalar(select(StudySeries.id).where(StudySeries.title == spec["title"])):
            continue
        items = list(spec["items"])
        if not items:
            roots = session.execute(
                select(Root.root_display).order_by(Root.occurrence_count.desc()).limit(20)
            ).all()
            items = [{"kind": "root", "target": r, "note": ""} for (r,) in roots]
        created.append(
            create_series(
                session,
                title=spec["title"],
                description=spec["description"],
                kind=spec["kind"],
                items=items,
                published=True,
            )["slug"]
        )
    return {"created": created, "total": session.scalar(select(func.count()).select_from(StudySeries))}
