"""Spaced-repetition trainer (Track F).

Three card kinds, all of which have a checkable answer in the corpus:

* ``reference_recall`` — given 2:255, recall the verse.
* ``morphology`` — given a word, name its root and part of speech.
* ``root_location`` — given a root, name a surah it occurs in.

**No card stores scripture.** A card stores a corpus key and both the prompt and
the answer are rendered from the database at review time. A stored copy is a
copy that can drift, and here the drift would end up in someone's memory.

**No meaning cards.** The obvious vocabulary card — root to gloss — cannot be
generated, because no lexicon is loaded and inventing a gloss would be teaching
someone a definition this application made up. The same gate as
``fields.distinctions``, and for the same reason. :func:`available_kinds` says
what is missing and what would unlock it.

Scheduling is SM-2. It is a convention with modest evidence behind it, not a
finding about memory, and the interval it returns is a suggestion about when to
look again rather than a claim about retention. :func:`review_stats` reports how
often cards the scheduler called due were actually remembered, because that is
the only honest self-assessment a scheduler has.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Ayah, Root, Segment, TrainerCard, TrainerReview, Word

KINDS = ("reference_recall", "morphology", "root_location")
# SM-2's floor. Below this the interval collapses and the card is shown
# constantly, which is how people abandon a deck.
MIN_EASE = 1.3
# A grade below this is a lapse: the card goes back to the start.
PASS_GRADE = 3
SEED = 20240617


class TrainerError(ValueError):
    pass


def available_kinds(session: Session) -> dict:
    """What can be drilled, and what cannot be until a lexicon is loaded."""
    from qra.models import Edition

    lexicons = session.scalars(
        select(Edition.slug).where(Edition.kind == "lexicon")
    ).all()
    return {
        "available": list(KINDS),
        "unavailable": []
        if lexicons
        else [
            {
                "kind": "vocabulary",
                "why": (
                    "A root-to-meaning card needs a gloss, and no lexicon edition is "
                    "loaded. Generating one would teach a definition this application "
                    "invented, which is the same failure as inventing scripture with the "
                    "consequence moved into the learner's memory."
                ),
                "unlocked_by": "qra ingest lexicon --slug lane",
            }
        ],
        "scheduling": (
            "SM-2. A convention with modest evidence behind it, not a finding about "
            "memory — the interval is a suggestion about when to look again."
        ),
    }


# ---------------------------------------------------------------------------
# Rendering: prompt and answer, always from the database
# ---------------------------------------------------------------------------


def render_card(session: Session, card: TrainerCard) -> dict:
    if card.kind == "reference_recall":
        surah, ayah = _parse_ref(card.subject)
        row = session.scalar(
            select(Ayah).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
        )
        if row is None:
            raise TrainerError(f"{card.subject} is not an ayah in this corpus")
        return {
            "prompt": f"Recall {card.subject}",
            # Rendered from the database. Never stored on the card.
            "answer": row.text_uthmani,
            "answer_kind": "scripture",
            "citation": {"ref": card.subject, "kind": "ayah"},
        }

    if card.kind == "morphology":
        word = session.get(Word, int(card.subject))
        if word is None:
            raise TrainerError(f"no word {card.subject}")
        segments = session.scalars(
            select(Segment).where(Segment.word_id == word.id).order_by(Segment.position)
        ).all()
        root = session.get(Root, word.root_id) if word.root_id else None
        return {
            "prompt": f"Root and part of speech for {word.text} ({word.surah_id}:{word.ayah_num})",
            "answer": {
                "root": root.root_display if root else None,
                "pos": word.pos,
                "segments": [
                    {"form": s.form, "pos_class": s.pos_class, "person": s.person}
                    for s in segments
                ],
            },
            "answer_kind": "morphology",
            "citation": {"ref": f"{word.surah_id}:{word.ayah_num}", "kind": "morphology"},
        }

    if card.kind == "root_location":
        row = session.scalar(select(Root).where(Root.root_display == card.subject))
        if row is None:
            raise TrainerError(f"no root {card.subject}")
        surahs = session.execute(
            select(Ayah.surah_id, func.count())
            .join(Segment, Segment.ayah_id == Ayah.id)
            .where(Segment.root_id == row.id)
            .group_by(Ayah.surah_id)
            .order_by(func.count().desc())
            .limit(8)
        ).all()
        return {
            "prompt": f"Name a surah where the root {row.root_display} occurs",
            "answer": {
                "surahs": [{"surah": s, "occurrences": n} for s, n in surahs],
                "total_occurrences": row.occurrence_count,
            },
            "answer_kind": "distribution",
            "citation": {"ref": row.root_display, "kind": "morphology"},
        }

    raise TrainerError(f"unknown card kind '{card.kind}'")


def _parse_ref(ref: str) -> tuple[int, int]:
    try:
        surah, ayah = (int(part) for part in ref.split(":", 1))
    except (ValueError, AttributeError) as exc:
        raise TrainerError(f"'{ref}' is not a reference like 2:255") from exc
    return surah, ayah


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def add_card(session: Session, user_id: int, *, kind: str, subject: str) -> dict:
    if kind not in KINDS:
        raise TrainerError(f"kind must be one of {', '.join(KINDS)}")
    existing = session.scalar(
        select(TrainerCard).where(
            TrainerCard.user_id == user_id,
            TrainerCard.kind == kind,
            TrainerCard.subject == subject,
        )
    )
    if existing is not None:
        return {"added": False, "already": True, "card_id": existing.id}

    card = TrainerCard(
        user_id=user_id, kind=kind, subject=subject, due_at=datetime.now(UTC)
    )
    # Validate by rendering *before* the row joins the session. A card whose
    # subject does not resolve fails silently at review time weeks later, and
    # adding it first meant a caught error left the bad row pending in the
    # transaction for whatever committed next.
    render_card(session, card)
    session.add(card)
    session.commit()
    return {"added": True, "card_id": card.id, "kind": kind, "subject": subject}


def seed_from_series(session: Session, user_id: int, series_id: int) -> dict:
    """Make cards from a series' items, skipping kinds that have no card form."""
    from qra.models import SeriesItem

    items = session.scalars(
        select(SeriesItem).where(SeriesItem.series_id == series_id).order_by(SeriesItem.position)
    ).all()
    added, skipped = 0, []
    for item in items:
        if item.kind == "ayah_range":
            first = item.target.split("-")[0]
            try:
                result = add_card(session, user_id, kind="reference_recall", subject=first)
            except TrainerError:
                skipped.append(item.target)
                continue
            added += 1 if result.get("added") else 0
        elif item.kind == "root":
            try:
                result = add_card(session, user_id, kind="root_location", subject=item.target)
            except TrainerError:
                skipped.append(item.target)
                continue
            added += 1 if result.get("added") else 0
        else:
            skipped.append(f"{item.kind}:{item.target}")
    return {
        "added": added,
        "skipped": skipped,
        "note": (
            "Concept and grammar-query items have no card form — they are things to read, "
            "not things to recall."
        ),
    }


def due(session: Session, user_id: int, *, limit: int = 20) -> dict:
    now = datetime.now(UTC)
    cards = session.scalars(
        select(TrainerCard)
        .where(TrainerCard.user_id == user_id, TrainerCard.due_at <= now)
        .order_by(TrainerCard.due_at)
        .limit(limit)
    ).all()
    total = (
        session.scalar(
            select(func.count()).select_from(TrainerCard).where(TrainerCard.user_id == user_id)
        )
        or 0
    )
    rendered = []
    for card in cards:
        try:
            payload = render_card(session, card)
        except TrainerError as exc:
            payload = {"prompt": f"[unresolvable: {exc}]", "answer": None, "answer_kind": "error"}
        rendered.append(
            {
                "card_id": card.id,
                "kind": card.kind,
                "subject": card.subject,
                "repetitions": card.repetitions,
                "interval_days": card.interval_days,
                **payload,
            }
        )
    return {
        "due": len(rendered),
        "total_cards": total,
        "cards": rendered,
        "note": (
            "Prompts and answers are rendered from the corpus at review time. No card "
            "stores scripture — a stored copy is one that can drift, and the drift would "
            "end up in your memory."
        ),
    }


def grade(session: Session, card_id: int, value: int) -> dict:
    """Apply SM-2 and schedule the next review.

    Grades run 0–5 as in the original algorithm; below 3 is a lapse and the card
    restarts. The ease floor matters more than it looks: without it a card that
    keeps failing gets a shorter and shorter interval until it appears every
    session, which is the point at which people stop using the deck.
    """
    card = session.get(TrainerCard, card_id)
    if card is None:
        raise TrainerError(f"no card {card_id}")
    if not 0 <= value <= 5:
        raise TrainerError("grade must be between 0 and 5")

    before = card.interval_days
    if value < PASS_GRADE:
        card.repetitions = 0
        card.interval_days = 1
        card.lapses += 1
    else:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval_days = 1
        elif card.repetitions == 2:
            card.interval_days = 6
        else:
            card.interval_days = max(1, round(card.interval_days * card.ease))

    card.ease = max(
        MIN_EASE, card.ease + (0.1 - (5 - value) * (0.08 + (5 - value) * 0.02))
    )
    card.last_grade = value
    card.due_at = datetime.now(UTC) + timedelta(days=card.interval_days)

    session.add(
        TrainerReview(
            card_id=card.id,
            grade=value,
            interval_before=before,
            interval_after=card.interval_days,
        )
    )
    session.commit()
    session.refresh(card)
    return {
        "card_id": card.id,
        "grade": value,
        "interval_days": card.interval_days,
        "ease": round(card.ease, 3),
        "repetitions": card.repetitions,
        "lapses": card.lapses,
        "due_at": card.due_at.isoformat(),
        "scheduling_note": (
            "SM-2. A scheduling convention, not a claim about your memory — see "
            "/study/trainer/stats for whether it has been right about you."
        ),
    }


def review_stats(session: Session, user_id: int) -> dict:
    """Has the scheduler been right?

    The only honest self-assessment available: of the cards it called due, how
    many were actually remembered. A scheduler that never reports this is
    asserting its intervals rather than testing them.
    """
    rows = session.execute(
        select(TrainerReview.grade, TrainerReview.interval_before)
        .join(TrainerCard, TrainerCard.id == TrainerReview.card_id)
        .where(TrainerCard.user_id == user_id)
    ).all()
    if not rows:
        return {
            "reviews": 0,
            "note": "No reviews yet. The scheduler has made no predictions to check.",
        }

    passed = sum(1 for g, _ in rows if g >= PASS_GRADE)
    # Split by whether the card had been scheduled out at all: a first sighting
    # says nothing about the interval, only about the material.
    scheduled = [(g, i) for g, i in rows if i > 0]
    scheduled_passed = sum(1 for g, _ in scheduled if g >= PASS_GRADE)
    return {
        "reviews": len(rows),
        "recall_rate": round(passed / len(rows), 3),
        "scheduled_reviews": len(scheduled),
        "scheduled_recall_rate": (
            round(scheduled_passed / len(scheduled), 3) if scheduled else None
        ),
        "target": 0.9,
        "reading": (
            "SM-2 aims for roughly 90% recall on scheduled reviews. Well below that means "
            "the intervals are too long for this material; well above means they are too "
            "short and the time is being wasted. Either way the number is about the "
            "schedule, not about the learner."
            if scheduled
            else "Only first sightings so far, which test the material rather than the "
            "interval. The schedule has not yet been put to the question."
        ),
    }


def suggest_cards(session: Session, *, kind: str = "root_location", count: int = 10) -> list[dict]:
    """Corpus items worth drilling, chosen by frequency rather than by taste."""
    rng = random.Random(SEED)
    if kind == "root_location":
        rows = session.execute(
            select(Root.root_display, Root.occurrence_count)
            .order_by(Root.occurrence_count.desc())
            .limit(60)
        ).all()
        picked = rng.sample(rows, min(count, len(rows)))
        return [{"subject": r, "occurrences": n, "kind": kind} for r, n in picked]
    if kind == "reference_recall":
        rows = session.execute(
            select(Ayah.surah_id, Ayah.ayah_num)
            .where(Ayah.word_count <= 12)
            .order_by(Ayah.id)
        ).all()
        picked = rng.sample(rows, min(count, len(rows)))
        return [{"subject": f"{s}:{a}", "kind": kind} for s, a in picked]
    raise TrainerError(f"no suggestions for kind '{kind}'")
