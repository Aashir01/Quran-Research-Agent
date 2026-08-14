"""Comparative narrative diff — the same story across many surahs, aligned.

The Musa narrative runs through 30+ surahs. Comparing tellings by hand is weeks
of work; with the morphology in place it is a query.

Passages are found from the data, not hand-curated: every ayah whose morphology
mentions the figure's lemma, merged into contiguous passages with a small gap
tolerance. That makes the method reproducible for any figure — Ibrahim, Nuh,
Yusuf, Maryam, 'Isa — instead of only for the stories someone typed up.

Motifs are content roots, filtered against corpus-wide frequency so that "said"
and "God" do not drown out "staff", "sea" and "magician". What each telling
adds, omits and reorders is then a set operation and a rank comparison.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.citations import ayah_citation
from qra.models import Ayah, Lemma, Root, Segment, Surah

# Figures with their Qur'anic lemma as the corpus writes it.
FIGURES = {
    "musa": {"lemma": "مُوسَىٰ", "label_en": "Musa (Moses)", "label_ur": "موسیٰ"},
    "ibrahim": {"lemma": "إِبْراهيم", "label_en": "Ibrahim (Abraham)", "label_ur": "ابراہیم"},
    "nuh": {"lemma": "نُوح", "label_en": "Nuh (Noah)", "label_ur": "نوح"},
    "yusuf": {"lemma": "يُوسُف", "label_en": "Yusuf (Joseph)", "label_ur": "یوسف"},
    "isa": {"lemma": "عيسىٰ", "label_en": "'Isa (Jesus)", "label_ur": "عیسیٰ"},
    "maryam": {"lemma": "مَرْيَم", "label_en": "Maryam (Mary)", "label_ur": "مریم"},
    "adam": {"lemma": "آدَم", "label_en": "Adam", "label_ur": "آدم"},
    "sulayman": {"lemma": "سُلَيْمان", "label_en": "Sulayman (Solomon)", "label_ur": "سلیمان"},
    "yunus": {"lemma": "يُونُس", "label_en": "Yunus (Jonah)", "label_ur": "یونس"},
    "hud": {"lemma": "هُود", "label_en": "Hud", "label_ur": "ہود"},
    "salih": {"lemma": "صالِح", "label_en": "Salih", "label_ur": "صالح"},
    "lut": {"lemma": "لُوط", "label_en": "Lut (Lot)", "label_ur": "لوط"},
}

# Roots this common carry no narrative signal.
_STOPWORD_MIN_OCCURRENCES = 500


def _figure_ayat(session: Session, figure: str) -> list[Ayah]:
    spec = FIGURES.get(figure)
    if spec is None:
        return []
    key = search_form(spec["lemma"])
    lemma_ids = list(session.scalars(select(Lemma.id).where(Lemma.lemma == key)).all())
    if not lemma_ids:
        return []
    return list(
        session.scalars(
            select(Ayah)
            .join(Segment, Segment.ayah_id == Ayah.id)
            .where(Segment.lemma_id.in_(lemma_ids))
            .distinct()
            .order_by(Ayah.id)
        ).all()
    )


def _merge_passages(ayat: list[Ayah], gap: int) -> list[list[Ayah]]:
    passages: list[list[Ayah]] = []
    current: list[Ayah] = []
    for ayah in ayat:
        if (
            current
            and ayah.surah_id == current[-1].surah_id
            and ayah.ayah_num - current[-1].ayah_num <= gap + 1
        ):
            current.append(ayah)
        else:
            if current:
                passages.append(current)
            current = [ayah]
    if current:
        passages.append(current)
    return passages


def _passage_span(session: Session, passage: list[Ayah], pad: int) -> list[Ayah]:
    """Widen a passage by ``pad`` ayat each side, clipped to the surah."""
    surah_id = passage[0].surah_id
    start = max(1, passage[0].ayah_num - pad)
    end = passage[-1].ayah_num + pad
    return list(
        session.scalars(
            select(Ayah)
            .where(Ayah.surah_id == surah_id, Ayah.ayah_num >= start, Ayah.ayah_num <= end)
            .order_by(Ayah.ayah_num)
        ).all()
    )


def narrative_passages(
    session: Session, figure: str, *, gap: int = 3, pad: int = 2, min_mentions: int = 1
) -> dict:
    """Locate every telling of a figure's story, with each passage's motifs."""
    spec = FIGURES.get(figure)
    if spec is None:
        return {"figure": figure, "found": False, "available": sorted(FIGURES)}

    mentions = _figure_ayat(session, figure)
    if not mentions:
        return {"figure": figure, "found": False, "reason": "lemma not found in corpus"}

    common_roots = {
        display
        for (display,) in session.execute(
            select(Root.root_display).where(Root.occurrence_count >= _STOPWORD_MIN_OCCURRENCES)
        ).all()
    }
    surahs = {s.id: s for s in session.scalars(select(Surah)).all()}

    passages = []
    for group in _merge_passages(mentions, gap):
        # A single mention still counts as a telling — the brief allusions are
        # part of what a comparative diff is for.
        if len(group) < min_mentions:
            continue
        span = _passage_span(session, group, pad)
        ayah_ids = [a.id for a in span]
        roots = Counter(
            display
            for (display,) in session.execute(
                select(Root.root_display)
                .join(Segment, Segment.root_id == Root.id)
                .where(Segment.ayah_id.in_(ayah_ids))
            ).all()
        )
        motifs = [r for r, _n in roots.most_common() if r not in common_roots]
        surah = surahs[span[0].surah_id]
        passages.append(
            {
                "surah": surah.id,
                "surah_name": surah.name_translit,
                "revelation_place": surah.revelation_place,
                "revelation_order": surah.revelation_order,
                "ayah_start": span[0].ayah_num,
                "ayah_end": span[-1].ayah_num,
                "ref": f"{surah.id}:{span[0].ayah_num}-{span[-1].ayah_num}",
                "ayah_count": len(span),
                "mention_count": len(group),
                "motifs": motifs[:40],
                "ayah_ids": ayah_ids,
                "citation": ayah_citation(span[0]).to_dict(),
            }
        )

    passages.sort(key=lambda p: (-p["ayah_count"], p["surah"]))
    return {
        "figure": figure,
        "label_en": spec["label_en"],
        "label_ur": spec["label_ur"],
        "found": True,
        "passage_count": len(passages),
        "total_ayat": sum(p["ayah_count"] for p in passages),
        "surahs": sorted({p["surah"] for p in passages}),
        "passages": passages,
        "method": (
            f"Ayat whose morphology carries the lemma {spec['lemma']}, merged into passages "
            f"with a gap tolerance of {gap} ayat and padded by {pad} on each side. "
            "Motifs are roots occurring fewer than "
            f"{_STOPWORD_MIN_OCCURRENCES} times corpus-wide."
        ),
    }


def narrative_diff(
    session: Session, figure: str, *, top_passages: int = 12, gap: int = 3, pad: int = 2
) -> dict:
    """Align the tellings and report what each adds, omits and reorders.

    The longest telling is the reference axis (not a claim that it is primary —
    it simply has the most material to align against), and every other passage
    is diffed against the union of motifs.
    """
    found = narrative_passages(session, figure, gap=gap, pad=pad)
    if not found.get("found"):
        return found

    passages = found["passages"][:top_passages]
    if not passages:
        return {**found, "diff": None}

    motif_sets = {p["ref"]: set(p["motifs"]) for p in passages}
    shared = set.intersection(*motif_sets.values()) if motif_sets else set()
    union: set[str] = set().union(*motif_sets.values()) if motif_sets else set()
    frequency = Counter()
    for motifs in motif_sets.values():
        frequency.update(motifs)

    reference = passages[0]
    reference_order = [m for m in reference["motifs"] if m in union]

    rows = []
    for passage in passages:
        motifs = motif_sets[passage["ref"]]
        others = union - motifs
        unique = {m for m in motifs if frequency[m] == 1}
        # Order comparison: motifs shared with the reference, in each telling's
        # own sequence, so a reordering is visible as a permutation.
        order_here = [m for m in passage["motifs"] if m in set(reference_order)]
        order_ref = [m for m in reference_order if m in set(order_here)]
        inversions = sum(
            1
            for i in range(len(order_here))
            for j in range(i + 1, len(order_here))
            if order_ref.index(order_here[i]) > order_ref.index(order_here[j])
        )
        pairs = max(1, len(order_here) * (len(order_here) - 1) // 2)
        rows.append(
            {
                "ref": passage["ref"],
                "surah": passage["surah"],
                "surah_name": passage["surah_name"],
                "revelation_place": passage["revelation_place"],
                "revelation_order": passage["revelation_order"],
                "ayah_count": passage["ayah_count"],
                "motif_count": len(motifs),
                "adds_vs_others": sorted(unique)[:15],
                "omits_vs_union": sorted(others)[:15],
                "shares_with_all": sorted(shared)[:15],
                "reorder_score": round(inversions / pairs, 3),
                "aligned_motifs": order_here[:20],
            }
        )

    return {
        **{k: v for k, v in found.items() if k != "passages"},
        "reference_passage": reference["ref"],
        "shared_by_all": sorted(shared),
        "motif_frequency": [
            {"motif": m, "in_passages": n} for m, n in frequency.most_common(40)
        ],
        "passages": rows,
        "reading": (
            "'adds_vs_others' lists motifs unique to that telling; 'omits_vs_union' lists motifs "
            "present elsewhere but absent here; 'reorder_score' is the share of motif pairs whose "
            "order differs from the reference telling (0 = same sequence, 1 = fully reversed). "
            "These are lexical signals meant to direct close reading, not a claim about meaning."
        ),
    }


def figures(session: Session) -> list[dict]:
    out = []
    for key, spec in FIGURES.items():
        count = session.scalar(
            select(func.count(func.distinct(Segment.ayah_id)))
            .join(Lemma, Lemma.id == Segment.lemma_id)
            .where(Lemma.lemma == search_form(spec["lemma"]))
        )
        out.append({"key": key, **spec, "ayah_mentions": int(count or 0)})
    return sorted(out, key=lambda f: -f["ayah_mentions"])
