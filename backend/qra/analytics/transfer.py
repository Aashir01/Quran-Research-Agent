"""Cross-corpus pattern transfer (WP-34).

The strongest available guard against mistaking language for message.

A root that clusters with another root in the Qur'an might be telling you
something about the Qur'an — or it might be telling you something about seventh
century Arabic, in which case the "pattern" is a property of the language and
carries no message at all. The only way to tell is to look at the same pattern
in a background corpus, and this repo has one: 34,178 hadith, same language,
same register, different author.

So every pattern view can ask: *does this hold in the background corpus too?*

* Holds in both → probably Arabic, not Qur'anic.
* Qur'an only → distinctive, and worth the researcher's attention.
* Background only → the Qur'an is doing something unusual by *omission*.

The comparison runs through the same null-model machinery as everything else
(:func:`qra.analytics.stats.assess`), so it cannot quietly use a friendlier
test than the finding it is checking.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.stats import assess
from qra.arabic import search_form
from qra.models import Ayah, Hadith, Root, Segment, Word

# The hadith corpus is not morphologically analysed, so background matching is
# on the folded surface form. That is weaker than the Qur'an side, and saying so
# is not a disclaimer — it is the reason the comparison is a *check*, not a
# finding in its own right.
BACKGROUND = "hadith"


def _quran_ayat_with_root(session: Session, root_id: int) -> set[int]:
    rows = session.execute(
        select(Segment.ayah_id).where(Segment.root_id == root_id).distinct()
    ).all()
    return {row[0] for row in rows}


def _root_surface_forms(session: Session, root_id: int, limit: int = 40) -> list[str]:
    """Surface forms of a root, for matching against an unanalysed corpus."""
    rows = session.execute(
        select(Segment.form_search, func.count())
        .where(Segment.root_id == root_id, Segment.form_search.is_not(None))
        .group_by(Segment.form_search)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [form for form, _ in rows if form and len(form) >= 3]


def _hadith_hits(session: Session, forms: list[str]) -> set[int]:
    """Narrations containing any surface form of the root."""
    if not forms:
        return set()
    clauses = [Hadith.text_search.like(f"%{form}%") for form in forms]
    from sqlalchemy import or_

    rows = session.execute(
        select(Hadith.id).where(Hadith.text_search.is_not(None), or_(*clauses))
    ).all()
    return {row[0] for row in rows}


def compare_pair(session: Session, root_a: str, root_b: str) -> dict:
    """Do these two roots co-occur in the Qur'an more than chance — and does the
    same hold in the hadith corpus?"""
    a = session.scalar(select(Root).where(Root.root == search_form(root_a)))
    b = session.scalar(select(Root).where(Root.root == search_form(root_b)))
    missing = [name for name, row in ((root_a, a), (root_b, b)) if row is None]
    if missing:
        return {
            "error": f"not in the corpus: {', '.join(missing)}",
            "roots": [root_a, root_b],
        }

    total_ayat = session.scalar(select(func.count()).select_from(Ayah)) or 1
    ayat_a = _quran_ayat_with_root(session, a.id)
    ayat_b = _quran_ayat_with_root(session, b.id)
    both = ayat_a & ayat_b
    quran = assess(
        len(both),
        len(ayat_a),
        len(ayat_b) / total_ayat,
        label=f"{a.root_display} with {b.root_display} in the Qur'an",
    )

    forms_a = _root_surface_forms(session, a.id)
    forms_b = _root_surface_forms(session, b.id)
    total_hadith = (
        session.scalar(
            select(func.count()).select_from(Hadith).where(Hadith.text_search.is_not(None))
        )
        or 1
    )
    hits_a = _hadith_hits(session, forms_a)
    hits_b = _hadith_hits(session, forms_b)
    hadith_both = hits_a & hits_b
    background = (
        assess(
            len(hadith_both),
            len(hits_a),
            len(hits_b) / total_hadith,
            label=f"{a.root_display} with {b.root_display} in hadith",
        )
        if hits_a and hits_b
        else None
    )

    return {
        "roots": [a.root_display, b.root_display],
        "quran": {
            "ayat_with_a": len(ayat_a),
            "ayat_with_b": len(ayat_b),
            "ayat_with_both": len(both),
            "universe": total_ayat,
            "significance": quran.to_dict(),
        },
        "background": {
            "corpus": BACKGROUND,
            "narrations_with_a": len(hits_a),
            "narrations_with_b": len(hits_b),
            "narrations_with_both": len(hadith_both),
            "universe": total_hadith,
            "significance": background.to_dict() if background else None,
            "matching": "folded surface forms — the hadith corpus carries no morphology",
        },
        **_verdict(quran, background),
    }


def _verdict(quran, background) -> dict:
    """Name what the comparison means, in the terms a researcher cares about."""
    quran_holds = not quran.within_chance
    background_holds = background is not None and not background.within_chance

    if quran_holds and background_holds:
        verdict = "general_arabic"
        reading = (
            "This association holds in the hadith corpus too. That points to a property of "
            "the language or the religious register rather than something distinctive to "
            "the Qur'an — the most common way a 'Qur'anic pattern' turns out not to be one."
        )
    elif quran_holds and background is not None:
        verdict = "distinctive"
        reading = (
            "Beyond chance in the Qur'an and within chance in the hadith corpus. That is a "
            "genuine contrast and worth pursuing — though the background corpus is matched on "
            "surface forms only, so treat it as a signal to investigate, not as settled."
        )
    elif not quran_holds and background_holds:
        verdict = "absent_in_quran"
        reading = (
            "The association is beyond chance in the background corpus but not in the Qur'an. "
            "An absence relative to ordinary usage can be as interesting as a presence."
        )
    elif background is None:
        verdict = "no_background"
        reading = (
            "Not enough background evidence to compare. Without it, a Qur'anic result cannot "
            "be told apart from a fact about Arabic."
        )
    else:
        verdict = "within_chance_in_both"
        reading = "Within chance in both corpora. There is no pattern here to explain."

    return {
        "verdict": verdict,
        "reading": reading,
        "caveat": (
            "The background corpus shares the Qur'an's language, register and period, which is "
            "what makes it a fair control — and also means an association found in both may "
            "still be theological rather than merely linguistic. This distinguishes "
            "'distinctive to this text' from 'true of this kind of Arabic'. It cannot "
            "distinguish language from message on its own."
        ),
    }


def compare_root(session: Session, root: str) -> dict:
    """How common is this root here versus in the background corpus?"""
    row = session.scalar(select(Root).where(Root.root == search_form(root)))
    if row is None:
        return {"error": f"root '{root}' is not in the corpus"}

    quran_words = session.scalar(select(func.count()).select_from(Word)) or 1
    quran_hits = (
        session.scalar(
            select(func.count()).select_from(Segment).where(Segment.root_id == row.id)
        )
        or 0
    )
    forms = _root_surface_forms(session, row.id)
    narrations = _hadith_hits(session, forms)
    total_hadith = (
        session.scalar(
            select(func.count()).select_from(Hadith).where(Hadith.text_search.is_not(None))
        )
        or 1
    )
    return {
        "root": row.root_display,
        "quran": {
            "occurrences": quran_hits,
            "per_1000_words": round(quran_hits / quran_words * 1000, 3),
            "words": quran_words,
        },
        "background": {
            "corpus": BACKGROUND,
            "narrations_containing": len(narrations),
            "share_of_narrations": round(len(narrations) / total_hadith, 4),
            "universe": total_hadith,
            "surface_forms_used": forms[:10],
        },
        "note": (
            "Rates are not directly comparable — one counts analysed segments, the other "
            "counts narrations containing a surface form. Use the ratio between two roots "
            "within each corpus, not the raw numbers across them."
        ),
    }


def offer(root_a: str, root_b: str) -> dict:
    """The background-comparison offer that rides along with a pattern view.

    WP-34's acceptance is that *every* pattern view offers this, not that a
    separate page exists where a researcher might think to look. A co-occurrence
    result that arrives without the question attached is a result that will be
    read as Qur'anic when it may only be Arabic — so the question travels with
    the finding, and the finding names the call that answers it.

    The comparison itself is not run inline: it is a full scan of 34k narrations
    and would put seconds on every pattern request. Offering is cheap; the
    researcher decides when to spend it.
    """
    return {
        "question": (
            "Does this hold in the hadith corpus too? If it does, it is likely a property "
            "of seventh-century Arabic rather than something distinctive to the Qur'an."
        ),
        "corpus": BACKGROUND,
        "endpoint": f"/analysis/transfer/pair?a={root_a}&b={root_b}",
        "why": (
            "The single most common way a 'Qur'anic pattern' turns out not to be one is that "
            "nobody checked the same pattern in ordinary Arabic of the same period."
        ),
    }
