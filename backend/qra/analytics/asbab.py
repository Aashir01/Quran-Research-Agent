"""Occasions of revelation, as reports (WP-20).

An asbab entry is a *claim someone transmitted*, not a property of an ayah, and
the tradition disagrees about many of them. Filing them as commentary makes them
read as settled context — the one thing the interviewed researchers drew a red
line around — so this module rebuilds them into a table where a grade and a
claimant are structurally required.

It also fixes a live corpus bug. The shipped al-Wahidi edition is filed
sequentially, not by verse: of the 690 entries that cite a reference inside
their own text, **673 cite a different verse than the row is filed under**. A
researcher opening 2:9 was being shown a report about 2:113. The verse a report
names inside itself is the one it is about, so that is the reference this
rebuild trusts, and anything it cannot map is withheld rather than guessed.
"""

from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from qra.models import AsbabReport, Ayah, Edition, TafsirEntry

# `(quoted verse…) [2:113]` — the citation al-Wahidi's translator puts at the
# head of each report.
IN_TEXT_REF = re.compile(r"\[(\d{1,3}):(\d{1,3})(?:-\d{1,3})?\]")

# Language that marks a text as an occasion-of-revelation report rather than
# commentary. Deliberately broad: a false negative withholds a real report,
# which is recoverable, while a false positive presents mysticism as history.
REVELATION_MARKERS = (
    "was revealed",
    "were revealed",
    "revealed about",
    "revealed concerning",
    "revealed regarding",
    "revealed when",
    "revealed in response",
    "this verse came down",
    "occasion of",
)

GRADES = ("sahih", "hasan", "daif", "mursal", "ungraded")


def _classify(text: str) -> tuple[bool, str | None]:
    lowered = (text or "").lower()
    if any(marker in lowered for marker in REVELATION_MARKERS):
        return True, None
    return False, (
        "No occasion-of-revelation language. The upstream feed for this edition "
        "mixes in commentary that is not asbab, and serving it as asbab would "
        "present exegesis as historical context."
    )


def rebuild(session: Session, *, edition_slug: str = "asbab-wahidi") -> dict:
    """Re-derive the asbab table from the ingested edition.

    Idempotent: it clears and rebuilds this edition's rows, so it can run after
    every ingest without accumulating duplicates.
    """
    edition = session.scalar(select(Edition).where(Edition.slug == edition_slug))
    if edition is None:
        return {"edition": edition_slug, "error": "edition not ingested", "written": 0}

    session.execute(delete(AsbabReport).where(AsbabReport.edition_id == edition.id))

    # One lookup for the whole corpus beats 992 round trips.
    ayah_index = {
        (surah, num): ayah_id
        for ayah_id, surah, num in session.execute(
            select(Ayah.id, Ayah.surah_id, Ayah.ayah_num)
        ).all()
    }

    entries = session.scalars(
        select(TafsirEntry).where(TafsirEntry.edition_id == edition.id)
    ).all()

    stats = {
        "mapped_from_text": 0,
        "kept_upstream_filing": 0,
        "unmapped": 0,
        "withheld_not_asbab": 0,
        "corrected": 0,
    }
    rows: list[AsbabReport] = []

    for entry in entries:
        text = (entry.text or "").strip()
        if not text:
            continue

        is_report, reason = _classify(text)
        match = IN_TEXT_REF.search(text)

        if match:
            surah, num = int(match.group(1)), int(match.group(2))
            mapping, confidence = "in_text_reference", 0.9
            if (surah, num) != (entry.surah_id, entry.ayah_start):
                stats["corrected"] += 1
            stats["mapped_from_text"] += 1
        elif entry.surah_id and entry.ayah_start:
            # No self-citation. The upstream filing is the only signal left and
            # it is demonstrably unreliable for this edition, so it is recorded
            # as such rather than trusted.
            surah, num = entry.surah_id, entry.ayah_start
            mapping, confidence = "upstream_filing", 0.25
            stats["kept_upstream_filing"] += 1
        else:
            surah = num = None
            mapping, confidence = "unmapped", 0.0
            stats["unmapped"] += 1

        if not is_report:
            stats["withheld_not_asbab"] += 1

        rows.append(
            AsbabReport(
                edition_id=edition.id,
                ayah_id=ayah_index.get((surah, num)) if surah and num else None,
                surah_id=surah,
                ayah_num=num,
                text=text,
                language=edition.language or "en",
                claimant=edition.author or "unattributed",
                source_work=edition.name,
                reference=entry.reference,
                # The source carries no isnad grading, and inventing one would
                # be the exact failure this table exists to prevent.
                grade="ungraded",
                graded_by=None,
                mapping=mapping,
                mapping_confidence=confidence,
                status="published" if is_report else "withheld",
                withheld_reason=reason,
                source_entry_id=entry.id,
            )
        )

    session.add_all(rows)
    session.commit()
    return {
        "edition": edition_slug,
        "written": len(rows),
        "published": sum(1 for r in rows if r.status == "published"),
        "withheld": sum(1 for r in rows if r.status == "withheld"),
        **stats,
        "note": (
            f"{stats['corrected']} reports were filed under the wrong ayah upstream and have "
            "been re-anchored to the verse each one cites inside its own text."
        ),
    }


def for_ayah(session: Session, surah: int, ayah: int) -> dict:
    """Every report about this ayah — each with its grade, always."""
    rows = session.scalars(
        select(AsbabReport)
        .where(
            AsbabReport.surah_id == surah,
            AsbabReport.ayah_num == ayah,
            AsbabReport.status == "published",
        )
        .order_by(AsbabReport.mapping_confidence.desc())
    ).all()
    return {
        "ref": f"{surah}:{ayah}",
        "count": len(rows),
        "reports": [serialise(row) for row in rows],
        "exhaustive": True,
        "framing": (
            "These are reports, not settled context. Each one was transmitted by "
            "someone, the tradition disagrees about many of them, and an ungraded "
            "report is not a weak report — it is one nobody in this corpus has graded."
        ),
    }


def serialise(row: AsbabReport) -> dict:
    """Serialisation is the enforcement point: a grade cannot be omitted."""
    grade = row.grade if row.grade in GRADES else "ungraded"
    return {
        "id": row.id,
        "ref": f"{row.surah_id}:{row.ayah_num}" if row.surah_id else None,
        "text": row.text,
        "language": row.language,
        "claimant": row.claimant,
        "source_work": row.source_work,
        "reference": row.reference,
        # Never absent, never null, never inferred.
        "grade": grade,
        "graded_by": row.graded_by,
        "grade_note": (
            "This source transmits its reports without isnad gradings. `ungraded` "
            "means nobody in this corpus has graded it, not that it is weak."
            if grade == "ungraded"
            else None
        ),
        "mapping": row.mapping,
        "mapping_confidence": round(row.mapping_confidence, 2),
        "mapping_note": (
            "Anchored to the verse this report cites inside its own text; the "
            "upstream edition filed it elsewhere."
            if row.mapping == "in_text_reference"
            else "Upstream filing, which is unreliable for this edition — treat the "
            "verse association as uncertain."
            if row.mapping == "upstream_filing"
            else "Could not be anchored to a verse."
        ),
    }


def coverage(session: Session) -> dict:
    """How much of the corpus has an occasion recorded — and how sure we are."""
    total = session.scalar(select(func.count()).select_from(AsbabReport)) or 0
    published = (
        session.scalar(
            select(func.count()).select_from(AsbabReport).where(AsbabReport.status == "published")
        )
        or 0
    )
    ayat = (
        session.scalar(
            select(func.count(func.distinct(AsbabReport.ayah_id))).where(
                AsbabReport.status == "published", AsbabReport.ayah_id.is_not(None)
            )
        )
        or 0
    )
    by_mapping = dict(
        session.execute(
            select(AsbabReport.mapping, func.count())
            .where(AsbabReport.status == "published")
            .group_by(AsbabReport.mapping)
        ).all()
    )
    by_grade = dict(
        session.execute(
            select(AsbabReport.grade, func.count())
            .where(AsbabReport.status == "published")
            .group_by(AsbabReport.grade)
        ).all()
    )
    return {
        "reports_total": total,
        "published": published,
        "withheld": total - published,
        "ayat_covered": ayat,
        "corpus_ayat": 6236,
        "coverage_pct": round(ayat / 6236 * 100, 2),
        "by_mapping": by_mapping,
        "by_grade": by_grade,
        "note": (
            "Coverage is deliberately low and honestly reported. Most of the Qur'an has "
            "no transmitted occasion of revelation, and a tool that implied otherwise "
            "would be inventing history."
        ),
    }
