"""Distribution analytics.

The important axis is **revelation order**, not mushaf order. Most claims about
how a theme develops are invisible when surahs are read 1..114 and obvious when
they are read 1st-revealed..114th-revealed. Every series here is available on
both axes, and the nuzul series always carries the caveat that the ordering
itself is a reconstruction.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.stats import assess, correct_multiple
from qra.arabic import normalise_root
from qra.config import settings
from qra.models import Ayah, Concept, ConceptAyah, Root, Segment, Surah


def _revelation_caveat() -> str:
    payload = json.loads((settings.metadata_dir / "revelation_order.json").read_text(encoding="utf-8"))
    return payload["caveat"]


def corpus_profile(session: Session) -> dict:
    total_words = session.scalar(select(func.sum(Ayah.word_count))) or 0
    total_segments = session.scalar(select(func.count()).select_from(Segment)) or 0
    by_place = dict(
        session.execute(
            select(Ayah.revelation_place, func.count()).group_by(Ayah.revelation_place)
        ).all()
    )
    words_by_place = dict(
        session.execute(
            select(Ayah.revelation_place, func.sum(Ayah.word_count)).group_by(Ayah.revelation_place)
        ).all()
    )
    return {
        "surahs": session.scalar(select(func.count()).select_from(Surah)),
        "ayat": session.scalar(select(func.count()).select_from(Ayah)),
        "words": int(total_words),
        "segments": int(total_segments),
        "roots": session.scalar(select(func.count()).select_from(Root)),
        "ayat_by_revelation_place": by_place,
        "words_by_revelation_place": {k: int(v) for k, v in words_by_place.items()},
    }


def root_distribution(session: Session, root: str, *, normalise: bool = True) -> dict:
    """Per-surah frequency of a root on both the mushaf and the nuzul axis.

    ``rate_per_1000`` is what you compare across surahs: al-Baqara has 6,140
    words and al-Kawthar has 10, so raw counts only ever tell you which surah is
    longer.
    """
    key = normalise_root(root)
    row = session.scalar(select(Root).where(Root.root == key))
    if row is None:
        return {"root": key, "found": False}

    counts = dict(
        session.execute(
            select(Segment.surah_id, func.count())
            .where(Segment.root_id == row.id)
            .group_by(Segment.surah_id)
        ).all()
    )
    surahs = session.scalars(select(Surah).order_by(Surah.id)).all()
    words_by_surah = dict(
        session.execute(select(Ayah.surah_id, func.sum(Ayah.word_count)).group_by(Ayah.surah_id)).all()
    )
    total_words = sum(int(v) for v in words_by_surah.values())
    corpus_rate = row.occurrence_count / total_words if total_words else 0.0

    series = []
    for surah in surahs:
        words = int(words_by_surah.get(surah.id, 0)) or 1
        count = counts.get(surah.id, 0)
        series.append(
            {
                "surah": surah.id,
                "name": surah.name_translit,
                "revelation_order": surah.revelation_order,
                "revelation_place": surah.revelation_place,
                "count": count,
                "words": words,
                "rate_per_1000": round(1000 * count / words, 3) if normalise else None,
            }
        )

    makki_words = sum(s["words"] for s in series if s["revelation_place"] == "makki")
    madani_words = sum(s["words"] for s in series if s["revelation_place"] == "madani")
    makki_count = sum(s["count"] for s in series if s["revelation_place"] == "makki")
    madani_count = sum(s["count"] for s in series if s["revelation_place"] == "madani")

    # Is the Makkan concentration more than the sizes of the two corpora explain?
    makki_share = makki_words / (makki_words + madani_words) if (makki_words + madani_words) else 0.5
    significance = assess(
        makki_count,
        makki_count + madani_count,
        makki_share,
        label=f"Makkan share of root {row.root_display}",
    )

    return {
        "root": row.root,
        "root_display": row.root_display,
        "found": True,
        "total_occurrences": row.occurrence_count,
        "total_ayat": row.ayah_count,
        "corpus_rate_per_1000": round(1000 * corpus_rate, 4),
        "by_mushaf_order": series,
        "by_revelation_order": sorted(series, key=lambda s: s["revelation_order"]),
        "makki_madani": {
            "makki": {"count": makki_count, "words": makki_words,
                       "rate_per_1000": round(1000 * makki_count / makki_words, 3) if makki_words else 0},
            "madani": {"count": madani_count, "words": madani_words,
                        "rate_per_1000": round(1000 * madani_count / madani_words, 3) if madani_words else 0},
            "significance": significance.to_dict(),
        },
        "revelation_order_caveat": _revelation_caveat(),
    }


def revelation_timeline(
    session: Session, roots: list[str], *, buckets: int = 12, normalise: bool = True
) -> dict:
    """Several roots plotted together along the revelation timeline.

    Surahs are grouped into equal-sized buckets of revelation order so a single
    long surah cannot dominate a point on the curve.
    """
    keys = [normalise_root(r) for r in roots]
    rows = {r.root: r for r in session.scalars(select(Root).where(Root.root.in_(keys))).all()}
    surahs = {s.id: s for s in session.scalars(select(Surah)).all()}
    words_by_surah = dict(
        session.execute(select(Ayah.surah_id, func.sum(Ayah.word_count)).group_by(Ayah.surah_id)).all()
    )

    ordered = sorted(surahs.values(), key=lambda s: s.revelation_order)
    size = max(1, len(ordered) // buckets)
    groups = [ordered[i : i + size] for i in range(0, len(ordered), size)]

    series = {}
    for key in keys:
        row = rows.get(key)
        if row is None:
            series[key] = None
            continue
        counts = dict(
            session.execute(
                select(Segment.surah_id, func.count())
                .where(Segment.root_id == row.id)
                .group_by(Segment.surah_id)
            ).all()
        )
        points = []
        for i, group in enumerate(groups):
            words = sum(int(words_by_surah.get(s.id, 0)) for s in group) or 1
            count = sum(counts.get(s.id, 0) for s in group)
            points.append(
                {
                    "bucket": i + 1,
                    "revelation_order_range": [group[0].revelation_order, group[-1].revelation_order],
                    "surahs": [s.id for s in group],
                    "makki_share": round(
                        sum(1 for s in group if s.revelation_place == "makki") / len(group), 2
                    ),
                    "count": count,
                    "words": words,
                    "rate_per_1000": round(1000 * count / words, 3) if normalise else None,
                }
            )
        series[row.root_display] = points

    return {
        "buckets": len(groups),
        "series": series,
        "axis": "revelation_order (egyptian_standard)",
        "caveat": _revelation_caveat(),
    }


def concept_distribution(session: Session, slug: str) -> dict:
    concept = session.scalar(select(Concept).where(Concept.slug == slug))
    if concept is None:
        return {"concept": slug, "found": False}
    counts = dict(
        session.execute(
            select(Ayah.surah_id, func.count())
            .join(ConceptAyah, ConceptAyah.ayah_id == Ayah.id)
            .where(ConceptAyah.concept_id == concept.id)
            .group_by(Ayah.surah_id)
        ).all()
    )
    by_place = dict(
        session.execute(
            select(Ayah.revelation_place, func.count())
            .join(ConceptAyah, ConceptAyah.ayah_id == Ayah.id)
            .where(ConceptAyah.concept_id == concept.id)
            .group_by(Ayah.revelation_place)
        ).all()
    )
    ayat_by_place = dict(
        session.execute(select(Ayah.revelation_place, func.count()).group_by(Ayah.revelation_place)).all()
    )
    total_ayat = sum(ayat_by_place.values())
    makki_share = ayat_by_place.get("makki", 0) / total_ayat if total_ayat else 0.5
    significance = assess(
        by_place.get("makki", 0),
        sum(by_place.values()),
        makki_share,
        label=f"Makkan share of concept '{slug}'",
    )
    surahs = {s.id: s for s in session.scalars(select(Surah)).all()}
    return {
        "concept": slug,
        "found": True,
        "label_en": concept.label_en,
        "total_ayat": sum(counts.values()),
        "by_revelation_place": by_place,
        "significance": significance.to_dict(),
        "by_revelation_order": [
            {
                "surah": sid,
                "revelation_order": surahs[sid].revelation_order,
                "count": n,
            }
            for sid, n in sorted(counts.items(), key=lambda kv: surahs[kv[0]].revelation_order)
        ],
        "provenance": "derived from concept->root map",
        "caveat": _revelation_caveat(),
    }


def makki_madani_sweep(session: Session, *, min_occurrences: int = 20, top: int = 40) -> dict:
    """Which roots are genuinely skewed Makkan or Madani?

    A sweep over ~800 roots, so multiple-comparison correction is not optional:
    it is applied before anything is returned, and the uncorrected list is not
    exposed at all.
    """
    words_by_place = dict(
        session.execute(
            select(Ayah.revelation_place, func.sum(Ayah.word_count)).group_by(Ayah.revelation_place)
        ).all()
    )
    makki_words = int(words_by_place.get("makki", 0))
    madani_words = int(words_by_place.get("madani", 0))
    makki_share = makki_words / (makki_words + madani_words)

    rows = session.execute(
        select(
            Root.root_display,
            func.count(Segment.id).filter(Ayah.revelation_place == "makki"),
            func.count(Segment.id).filter(Ayah.revelation_place == "madani"),
        )
        .join(Segment, Segment.root_id == Root.id)
        .join(Ayah, Ayah.id == Segment.ayah_id)
        .group_by(Root.root_display)
        .having(func.count(Segment.id) >= min_occurrences)
    ).all()

    results = []
    labels = []
    for display, makki, madani in rows:
        results.append(
            assess(makki, makki + madani, makki_share, label=f"root {display} Makkan share")
        )
        labels.append({"root": display, "makki": makki, "madani": madani})
    correct_multiple(results)

    combined = [
        {
            **label,
            "makki_rate_per_1000": round(1000 * label["makki"] / makki_words, 3),
            "madani_rate_per_1000": round(1000 * label["madani"] / madani_words, 3),
            "significance": result.to_dict(),
        }
        for label, result in zip(labels, results, strict=True)
        if not result.within_chance
    ]
    combined.sort(key=lambda r: r["significance"]["corrected_p"])

    return {
        "tested_roots": len(results),
        "surviving_correction": len(combined),
        "baseline_makki_word_share": round(makki_share, 4),
        "results": combined[:top],
        "method": "exact binomial per root, Benjamini-Hochberg across the family",
        "caveat": _revelation_caveat(),
    }
