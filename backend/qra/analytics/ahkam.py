"""Ayat al-ahkam: legal verses, and the range of positions on them (WP-29).

Two halves that must not be allowed to blur into each other.

**The verses are findable.** A legal verse announces itself grammatically: an
imperative, a prohibition, ``كُتِبَ عَلَيْكُم`` (it is prescribed for you),
``أُحِلَّ`` / ``حُرِّمَتْ`` (made lawful / forbidden), the ``حدود الله`` formula, a
conditional whose consequence is an obligation. Those are morphological facts
and this module counts them exhaustively.

**The rulings are not.** Which verse establishes which obligation, and under
what conditions, is the subject matter of a thousand years of disagreement
between schools that each read the same Arabic. Invariant 4 — four positions
stay four positions — binds hardest here.

So the schema separates them. Verses come from the morphology.
:class:`~qra.models.MadhhabPosition` rows come from named works, and
:func:`topic` **refuses to present a ruling** until more than one school's
position is recorded. Not "shows a warning" — refuses. A single stored position
rendered as the answer is how a research tool becomes a fatwa engine, and the
distance between those two things is the reason this application exists.

The position table ships empty. That is not an unfinished feature; it is the
feature. Inventing four madhhab positions to make a screen look complete would
be a fabrication with a jurisprudential consequence.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.models import Ayah, ConditionalStructure, MadhhabPosition, Root, Segment, Surah


class AhkamError(ValueError):
    pass


MADHAHIB = (
    "hanafi",
    "maliki",
    "shafii",
    "hanbali",
    "jafari",
    "zaydi",
    "ibadi",
    "zahiri",
    "other",
)

# The classical estimates of how many ayat are legal range from about 150 to
# over 500 depending on how indirect a ruling may be and still count. That
# spread is itself the reason this module reports markers rather than a number.
CLASSICAL_RANGE = (150, 500)


@dataclass(frozen=True)
class Topic:
    slug: str
    label_en: str
    label_ar: str
    roots: tuple[str, ...]
    note: str = ""


TOPICS: tuple[Topic, ...] = (
    Topic("salah", "Prayer", "الصلاة", ("صلو", "وضأ", "قبل", "سجد", "ركع", "طهر")),
    Topic("sawm", "Fasting", "الصيام", ("صوم", "رمض", "فطر", "هلل")),
    Topic("zakah", "Zakat and alms", "الزكاة والصدقات", ("زكو", "صدق", "نفق", "فقر", "سكن")),
    Topic("hajj", "Pilgrimage", "الحج", ("حجج", "عمر", "هدي", "طوف", "حرم")),
    Topic("nikah", "Marriage", "النكاح", ("نكح", "زوج", "مهر", "ولي", "حرم")),
    Topic("talaq", "Divorce and waiting periods", "الطلاق والعدة", ("طلق", "عدد", "ظهر", "لعن", "رجع")),
    Topic("mirath", "Inheritance", "المواريث", ("ورث", "وصي", "نصف", "ثلث", "سهم")),
    Topic(
        "muamalat",
        "Contracts and transactions",
        "المعاملات",
        ("بيع", "ربو", "قرض", "رهن", "كيل", "وزن", "شهد", "كتب"),
        note="كتب is here for the debt-recording command of 2:282, the longest ayah in the Qur'an.",
    ),
    Topic("hudud", "Prescribed penalties", "الحدود", ("حدد", "زني", "سرق", "قذف", "جلد", "قطع")),
    Topic("qisas", "Retaliation and blood money", "القصاص والدية", ("قصص", "قتل", "دوي", "عفو")),
    Topic("atima", "Food and drink", "الأطعمة والأشربة", ("أكل", "طعم", "ذبح", "خمر", "لحم", "دمم")),
    Topic("ayman", "Oaths and vows", "الأيمان والنذور", ("حلف", "قسم", "يمن", "نذر", "كفر")),
    Topic("jihad-ahkam", "Rules of war and treaty", "أحكام الجهاد", ("قتل", "أسر", "عهد", "صلح", "غنم")),
    Topic("libas", "Dress and modesty", "اللباس والستر", ("خمر", "جلب", "زين", "غضض", "عور")),
)

BY_SLUG = {t.slug: t for t in TOPICS}

# Deterministic legal markers over the morphology. Each is a fact about the
# text; whether a marked verse *is* a legal verse is a judgement, which is why
# this returns marker counts rather than a verdict.
MARKER_FORMS = {
    "prescribed": ("كتب علىكم", "كتب عليكم"),
    "made_lawful": ("أحل", "احل"),
    "forbidden": ("حرمت", "حرم علىكم", "حرم عليكم"),
    "limits_of_god": ("حدود الله",),
}


def _topic_ayat(session: Session, topic: Topic) -> set[int]:
    keys = [search_form(r) for r in topic.roots]
    ids = session.scalars(select(Root.id).where(Root.root.in_(keys))).all()
    rows = session.execute(
        select(Segment.ayah_id).where(Segment.root_id.in_(ids)).distinct()
    ).all()
    return {row[0] for row in rows}


def _marked_ayat(session: Session) -> dict[str, set[int]]:
    """Ayat carrying an explicit legal marker."""
    marked: dict[str, set[int]] = {}
    for name, forms in MARKER_FORMS.items():
        clauses = [Ayah.text_search.like(f"%{search_form(f)}%") for f in forms]
        rows = session.execute(select(Ayah.id).where(or_(*clauses))).all()
        marked[name] = {row[0] for row in rows}

    # Imperatives and prohibitions, from the morphology rather than the surface.
    # IMPV is an *aspect* value in this annotation, not a mood — the mood slot
    # holds IND/SUBJ/JUS. Reading it from the wrong column returns zero rows and
    # looks exactly like "the Qur'an contains no imperatives".
    marked["imperative"] = {
        row[0]
        for row in session.execute(
            select(Segment.ayah_id).where(Segment.pos_class == "V", Segment.aspect == "IMPV")
        ).all()
    }
    # The jussive is how prohibition is formed (لا تفعل), so it is a legal
    # marker in its own right — and much the commonest one.
    marked["jussive"] = {
        row[0]
        for row in session.execute(
            select(Segment.ayah_id).where(Segment.pos_class == "V", Segment.mood == "JUS")
        ).all()
    }
    return marked


def positions(session: Session, slug: str) -> list[dict]:
    rows = session.scalars(
        select(MadhhabPosition).where(MadhhabPosition.topic == slug).order_by(MadhhabPosition.id)
    ).all()
    return [
        {
            "madhhab": row.madhhab,
            "position": row.position,
            "scholar": row.scholar,
            "source_work": row.source_work,
            "reasoning": row.reasoning,
            "ayah_id": row.ayah_id,
            "notes": row.notes,
        }
        for row in rows
    ]


def record_position(
    session: Session,
    *,
    topic: str,
    madhhab: str,
    position: str,
    source_work: str,
    scholar: str | None = None,
    ayah_ref: str | None = None,
    reasoning: str = "",
    notes: str | None = None,
) -> dict:
    """Record one school's position. Every field that carries authority is required."""
    if topic not in BY_SLUG:
        raise AhkamError(f"no legal topic '{topic}'; try one of {', '.join(BY_SLUG)}")
    if madhhab not in MADHAHIB:
        raise AhkamError(f"madhhab must be one of {', '.join(MADHAHIB)}")
    if not (position or "").strip():
        raise AhkamError("a position needs its content")
    if not (source_work or "").strip():
        raise AhkamError(
            "name the work this position is taken from. An unattributed position is an "
            "assertion about the law, and this table exists so that cannot be stored."
        )

    ayah_id = None
    if ayah_ref:
        try:
            surah, ayah = (int(part) for part in ayah_ref.split(":", 1))
        except ValueError as exc:
            raise AhkamError(f"'{ayah_ref}' is not a reference like 2:282") from exc
        ayah_id = session.scalar(
            select(Ayah.id).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
        )
        if ayah_id is None:
            raise AhkamError(f"{ayah_ref} is not an ayah in this corpus")

    row = MadhhabPosition(
        topic=topic,
        madhhab=madhhab,
        position=position.strip(),
        source_work=source_work.strip(),
        scholar=scholar,
        ayah_id=ayah_id,
        reasoning=reasoning,
        notes=notes,
    )
    session.add(row)
    session.commit()
    return {"recorded": True, "topic": topic, "madhhab": madhhab, "positions_now": len(positions(session, topic))}


def topic(session: Session, slug: str, *, limit: int = 40) -> dict:
    """One legal topic: its verses, its markers, and the range of positions.

    The acceptance criterion for WP-29 lives in ``ruling``: it is ``None``
    whenever fewer than two schools are on record, and the payload says why
    rather than showing the one position that happens to be stored.
    """
    spec = BY_SLUG.get(slug)
    if spec is None:
        raise AhkamError(f"no legal topic '{slug}'; try one of {', '.join(BY_SLUG)}")

    ayat = _topic_ayat(session, spec)
    marked = _marked_ayat(session)
    any_marker = set().union(*marked.values()) if marked else set()
    legal = ayat & any_marker

    refs = session.execute(
        select(Ayah.surah_id, Ayah.ayah_num, Surah.revelation_place)
        .join(Surah, Surah.id == Ayah.surah_id)
        .where(Ayah.id.in_(legal))
        .order_by(Ayah.id)
    ).all()
    conditionals = (
        session.scalar(
            select(func.count())
            .select_from(ConditionalStructure)
            .where(ConditionalStructure.ayah_id.in_(legal))
        )
        or 0
    )

    recorded = positions(session, slug)
    schools = sorted({p["madhhab"] for p in recorded})

    return {
        "slug": spec.slug,
        "label_en": spec.label_en,
        "label_ar": spec.label_ar,
        "note": spec.note,
        "roots": list(spec.roots),
        "ayat_with_topic_vocabulary": len(ayat),
        "ayat_also_carrying_a_legal_marker": len(legal),
        "markers_present": {
            name: len(ayat & ids) for name, ids in marked.items() if ayat & ids
        },
        "conditional_structures": conditionals,
        "verses": [
            {"ref": f"{s}:{a}", "revelation_place": place} for s, a, place in refs[:limit]
        ],
        "verses_returned": min(len(refs), limit),
        "exhaustive": True,
        # --- the half that is not computable ---
        "positions": recorded,
        "schools_on_record": schools,
        "ruling": None,
        "why_no_ruling": (
            "This view does not render a ruling. It renders the verses and, separately, the "
            "positions on record with their sources. "
            + (
                f"Only {len(schools)} school is on record for this topic, and showing one "
                "position as the answer is exactly how a research tool turns into a fatwa "
                "engine."
                if len(schools) == 1
                else "No positions are recorded for this topic yet. The table ships empty "
                "because populating it is scholarly work with sources attached."
                if not schools
                else f"{len(schools)} schools are on record below. They are shown as a range, "
                "not resolved into one answer — resolving them is the reader's work and their "
                "madhhab's, not this tool's."
            )
        ),
        "invariant": (
            "Four positions stay four positions. Where the schools differ, the difference is "
            "the finding."
        ),
    }


def survey(session: Session) -> dict:
    """Every legal topic, sized — with the classical disagreement about the count."""
    marked = _marked_ayat(session)
    any_marker = set().union(*marked.values()) if marked else set()
    total = session.scalar(select(func.count()).select_from(Ayah)) or 1

    entries = []
    for spec in TOPICS:
        ayat = _topic_ayat(session, spec)
        recorded = positions(session, spec.slug)
        entries.append(
            {
                "slug": spec.slug,
                "label_en": spec.label_en,
                "label_ar": spec.label_ar,
                "ayat_with_vocabulary": len(ayat),
                "ayat_with_marker": len(ayat & any_marker),
                "schools_on_record": len({p["madhhab"] for p in recorded}),
            }
        )
    return {
        "topics": entries,
        "ayat_carrying_any_legal_marker": len(any_marker),
        "corpus_ayat": total,
        "markers": {name: len(ids) for name, ids in marked.items()},
        "classical_estimates": {
            "range": list(CLASSICAL_RANGE),
            "note": (
                "Classical counts of ayat al-ahkam run from about 150 to over 500, depending "
                "on whether a verse must state a ruling directly or may imply one. This "
                "module therefore reports which markers a verse carries rather than "
                "declaring a total, because the total is the disagreement."
            ),
        },
        "positions_recorded": session.scalar(
            select(func.count()).select_from(MadhhabPosition)
        )
        or 0,
        "positions_note": (
            "The position table ships empty. That is the design: four positions stay four "
            "positions, and inventing them to fill a screen would be a fabrication with a "
            "jurisprudential consequence."
        ),
    }
