"""Semantic fields, built from distribution and gated on the lexicons (WP-28).

A "semantic field" for a concept is the set of words that live around it: its
near-synonyms, the words it stands against, the roots it keeps company with,
and how all of that moves across the revelation.

Three of those four are computable from the corpus. The fourth — the
*distinctions* between near-synonyms — is not, and that is the hard part of this
module.

**What distribution can do.** Two roots used in the same contexts are related.
That is second-order co-occurrence: build each root's profile of PMI-weighted
partners and compare profiles. It is a real, well-defined measurement and it
finds real relationships.

**What distribution cannot do.** It cannot tell you *which* relationship. The
classical result in distributional semantics is that antonyms have nearly
identical distributions — ``حق`` and ``باطل`` appear in the same contexts
precisely because they are opposed. So this module never calls a neighbour a
synonym. It reports distributional neighbours and, separately, marks the ones
whose first-order co-occurrence is also elevated, because juxtaposition of
opposites (طباق) is itself a Qur'anic figure and shows up as exactly that
signature.

**What only a lexicon can do.** ``علم`` versus ``معرفة``, ``خوف`` versus
``خشية`` — the distinctions al-Raghib draws in the *Mufradat* are lexicographic
judgements with a citable source. If no lexicon edition is loaded, this module
says the distinctions are unavailable. It does not infer them from counts and
present the inference as a distinction, which would be the whole failure this
application exists to avoid.
"""

from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.cooccurrence import _total_units, _units_for_root
from qra.analytics.stats import assess, correct_multiple
from qra.arabic import search_form
from qra.models import (
    Ayah,
    Concept,
    ConceptRoot,
    Edition,
    LexiconEntry,
    Root,
    Segment,
    Surah,
)

# A neighbour needs enough of a profile to compare. Below this the cosine is
# dominated by one or two shared partners and means nothing.
MIN_PROFILE = 4
MIN_OCCURRENCES = 8
NEIGHBOURS = 12


_PROFILE_CACHE: dict[int, dict[int, float]] | None = None


def _profiles(session: Session) -> dict[int, dict[int, float]]:
    """PMI-weighted partner profile for every root, per ayah.

    One query for the whole corpus rather than one per root: at 1,651 roots the
    per-root version is 1,651 round trips, and the result is the same matrix.
    """
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None:
        return _PROFILE_CACHE

    rows = session.execute(
        select(Segment.ayah_id, Segment.root_id)
        .where(Segment.root_id.is_not(None))
        .distinct()
    ).all()

    by_ayah: dict[int, set[int]] = {}
    counts: dict[int, int] = {}
    for ayah_id, root_id in rows:
        by_ayah.setdefault(ayah_id, set()).add(root_id)
    for roots in by_ayah.values():
        for root_id in roots:
            counts[root_id] = counts.get(root_id, 0) + 1

    total = len(by_ayah) or 1
    pairs: dict[int, dict[int, int]] = {}
    for roots in by_ayah.values():
        ordered = sorted(roots)
        for index, a in enumerate(ordered):
            forward = pairs.setdefault(a, {})
            for b in ordered[index + 1 :]:
                forward[b] = forward.get(b, 0) + 1
                back = pairs.setdefault(b, {})
                back[a] = back.get(a, 0) + 1

    profiles: dict[int, dict[int, float]] = {}
    for root_id, partners in pairs.items():
        p_a = counts[root_id] / total
        vector: dict[int, float] = {}
        for partner, shared in partners.items():
            p_ab = shared / total
            p_b = counts[partner] / total
            pmi = math.log2(p_ab / (p_a * p_b))
            # Positive PMI only. A negative value means "these avoid each other",
            # which is information, but mixing it into a similarity vector makes
            # co-absence look like co-presence.
            if pmi > 0:
                vector[partner] = pmi
        if len(vector) >= MIN_PROFILE:
            profiles[root_id] = vector
    # The corpus is closed and does not change between ingests, so this matrix
    # is computed once per process rather than on every field request.
    _PROFILE_CACHE = profiles
    return profiles


def reset_cache() -> None:
    """Drop the cached matrix — for tests, and after a re-ingest."""
    global _PROFILE_CACHE
    _PROFILE_CACHE = None


def _cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    dot = sum(weight * b.get(key, 0.0) for key, weight in a.items())
    if dot == 0:
        return 0.0
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    return dot / (norm_a * norm_b)


def neighbours(session: Session, root: str, *, limit: int = NEIGHBOURS) -> dict:
    """Roots used in the same contexts as this one.

    Deliberately not called synonyms. See the module docstring: antonyms score
    high here by construction, which is a property of the method and not a fault
    in it — provided nobody labels the output "synonym".
    """
    key = search_form(root)
    row = session.scalar(select(Root).where(Root.root == key))
    if row is None:
        return {"found": False, "root": root}

    profiles = _profiles(session)
    target = profiles.get(row.id)
    if target is None:
        return {
            "found": True,
            "root": row.root_display,
            "neighbours": [],
            "why_empty": (
                f"this root co-occurs with fewer than {MIN_PROFILE} partners above chance, "
                "so it has no profile to compare"
            ),
        }

    displays = dict(session.execute(select(Root.id, Root.root_display)).all())
    counts = dict(
        session.execute(
            select(Segment.root_id, func.count(func.distinct(Segment.ayah_id)))
            .where(Segment.root_id.is_not(None))
            .group_by(Segment.root_id)
        ).all()
    )

    scored = [
        (other, _cosine(target, vector))
        for other, vector in profiles.items()
        if other != row.id and counts.get(other, 0) >= MIN_OCCURRENCES
    ]
    scored.sort(key=lambda pair: -pair[1])
    top = scored[:limit]

    # Second pass: does the neighbour also sit in the *same ayah* more than
    # chance? Distributional similarity plus elevated juxtaposition is the
    # signature of antithesis, which classical rhetoric calls tibaq.
    total = _total_units(session, "ayah")
    units_a = _units_for_root(session, row.id, "ayah")
    results = []
    significances = []
    for other, similarity in top:
        units_b = _units_for_root(session, other, "ayah")
        shared = len(units_a & units_b)
        significance = assess(
            shared,
            len(units_a),
            len(units_b) / total,
            label=f"{row.root_display}+{displays[other]} in one ayah",
        )
        significances.append(significance)
        results.append(
            {
                "root": displays[other],
                "similarity": round(similarity, 4),
                "ayat_with_root": counts.get(other, 0),
                "shared_ayat": shared,
            }
        )
    correct_multiple(significances)
    for entry, significance in zip(results, significances, strict=True):
        payload = significance.to_dict()
        entry["juxtaposition"] = payload
        # Lift, not significance. Every distributional neighbour co-occurs beyond
        # chance — that is what makes it a neighbour — so a p-value cannot
        # separate them. How far past chance is what varies, and by a lot: for
        # هدي, ضلل lands at seven times expected while أله lands at 1.6.
        expected = payload.get("expected") or 0.0
        entry["lift"] = round(entry["shared_ayat"] / expected, 2) if expected else None
        entry["provenance"] = "system_suggested"

    with_lift = [e for e in results if e["lift"] is not None]
    ranked = sorted(with_lift, key=lambda e: -e["lift"])
    # Ranked within this root's own neighbours, not thresholded against a number
    # chosen to make the output look right. The top quarter is a place to look.
    cut = max(len(ranked) // 4, 1)
    juxtaposed = {id(e) for e in ranked[:cut]}
    for entry in results:
        top = id(entry) in juxtaposed
        entry["relation"] = "most_juxtaposed" if top else "shares_contexts"
        entry["reading"] = (
            "Among the neighbours this root is placed alongside far more than expected. "
            "Qur'anic style pairs opposites deliberately — tibaq — so the high-lift "
            "neighbours are where to check whether the relationship is contrast rather "
            "than similarity. The measure cannot tell you which; it tells you where to look."
            if top
            else "Used in similar contexts, without standout co-placement in a single ayah."
        )

    return {
        "found": True,
        "root": row.root_display,
        "method": (
            "Second-order co-occurrence: each root is a vector of positive-PMI ayah-level "
            "partners, compared by cosine. Neighbours are then checked for elevated "
            "co-placement within a single ayah against a binomial null."
        ),
        "warning": (
            "These are distributional neighbours, not synonyms. Words that are opposites "
            "share contexts almost perfectly — هدي's nearest neighbour in this corpus is "
            "ضلل, and أمن's third is كفر — so the label 'synonym' is never applied here by "
            "machine. Note also that a root occurring across a large share of the corpus "
            "(أله is in more than a third of ayat) will be a near neighbour of almost "
            "everything; `ayat_with_root` is given on each row so that can be discounted."
        ),
        "neighbours": results,
    }


def _lexicon_entries(session: Session, root_id: int) -> list[dict]:
    rows = session.execute(
        select(LexiconEntry, Edition)
        .join(Edition, Edition.id == LexiconEntry.edition_id)
        .where(LexiconEntry.root_id == root_id)
    ).all()
    return [
        {
            "edition": edition.name,
            "slug": edition.slug,
            "headword": entry.headword,
            "text": entry.text,
            "reference": entry.reference,
        }
        for entry, edition in rows
    ]


def distinctions(session: Session, roots: list[str]) -> dict:
    """What the lexicons say separates these roots — or that nothing is loaded.

    This is the part of a semantic field that cannot be computed. Either a
    lexicon edition is present and the distinction is quoted with its citation,
    or it is absent and this says so. There is no third branch that infers a
    distinction from frequency and prints it in the same typeface as a citation.
    """
    resolved = []
    for name in roots:
        row = session.scalar(select(Root).where(Root.root == search_form(name)))
        if row is None:
            resolved.append({"requested": name, "found": False})
            continue
        resolved.append(
            {
                "requested": name,
                "found": True,
                "root": row.root_display,
                "lexicon_entries": _lexicon_entries(session, row.id),
            }
        )

    loaded = session.scalars(select(Edition).where(Edition.kind == "lexicon")).all()
    available = any(entry.get("lexicon_entries") for entry in resolved)
    return {
        "roots": resolved,
        "lexicon_editions_loaded": [e.slug for e in loaded],
        "available": available,
        "note": (
            "Distinctions are quoted from the loaded lexicons with their references."
            if available
            else (
                "No lexicon edition is loaded, so the distinctions between these roots are "
                "not available. They are lexicographic judgements — al-Raghib's Mufradat on "
                "علم against معرفة, or خوف against خشية — and they cannot be recovered from "
                "distribution. Frequency can show that two roots are used differently; only "
                "a lexicographer can say what the difference *is*. Load one with "
                "`qra ingest lexicon --slug mufradat` (see qra.sources for licensing)."
            )
        ),
    }


def _nuzul_spread(session: Session, root_id: int) -> dict:
    rows = session.execute(
        select(Surah.revelation_order, func.count(func.distinct(Segment.ayah_id)))
        .join(Ayah, Ayah.surah_id == Surah.id)
        .join(Segment, Segment.ayah_id == Ayah.id)
        .where(Segment.root_id == root_id, Surah.revelation_order.is_not(None))
        .group_by(Surah.revelation_order)
        .order_by(Surah.revelation_order)
    ).all()
    if not rows:
        return {"buckets": [], "note": "no revelation-order data for this root"}

    orders = [order for order, _ in rows]
    span = max(orders) - min(orders) + 1
    size = max(span // 6, 1)
    buckets: dict[int, int] = {}
    for order, count in rows:
        buckets[(order - min(orders)) // size] = buckets.get((order - min(orders)) // size, 0) + count
    return {
        "buckets": [{"bucket": b, "ayat": buckets[b]} for b in sorted(buckets)],
        "first_revealed_surah_order": min(orders),
        "last_revealed_surah_order": max(orders),
        "note": (
            "Revelation order follows the traditional Egyptian sequence, which is itself a "
            "scholarly reconstruction and disputed at the margins. Read the shape, not the "
            "bucket boundaries."
        ),
    }


def field(session: Session, name: str, *, limit: int = NEIGHBOURS) -> dict:
    """The full semantic field for a root or a concept slug."""
    concept = session.scalar(select(Concept).where(Concept.slug == name))
    if concept is not None:
        roots = session.scalars(
            select(Root)
            .join(ConceptRoot, ConceptRoot.root_id == Root.id)
            .where(ConceptRoot.concept_id == concept.id)
        ).all()
        if not roots:
            return {"error": f"concept '{name}' has no roots mapped"}
        head = roots[0]
        label = concept.label_en
    else:
        head = session.scalar(select(Root).where(Root.root == search_form(name)))
        if head is None:
            return {"error": f"'{name}' is neither a concept slug nor a root in the corpus"}
        roots = [head]
        label = head.root_display

    occurrences = (
        session.scalar(
            select(func.count()).select_from(Segment).where(Segment.root_id == head.id)
        )
        or 0
    )
    ayat = (
        session.scalar(
            select(func.count(func.distinct(Segment.ayah_id))).where(Segment.root_id == head.id)
        )
        or 0
    )
    near = neighbours(session, head.root_display, limit=limit)
    found = near.get("neighbours", [])
    related = [n for n in found if n["relation"] == "shares_contexts"]
    opposed = [n for n in found if n["relation"] == "most_juxtaposed"]

    return {
        "query": name,
        "label": label,
        "head_root": head.root_display,
        "concept": concept.slug if concept else None,
        "roots_in_concept": [r.root_display for r in roots],
        "occurrences": occurrences,
        "ayat": ayat,
        "distributional_neighbours": sorted(related, key=lambda n: -(n["lift"] or 0)),
        "most_juxtaposed": sorted(opposed, key=lambda n: -(n["lift"] or 0)),
        "juxtaposition_note": (
            "Neighbours placed alongside this root far more than chance predicts. Check these "
            "for contrast (tibaq) as much as for similarity — the measure does not "
            "distinguish the two."
        ),
        "method": near.get("method"),
        "warning": near.get("warning"),
        "nuzul": _nuzul_spread(session, head.id),
        # The part that cannot be computed, kept structurally separate from the
        # parts that can, so a reader never mistakes one for the other.
        "distinctions": distinctions(
            session, [head.root_display, *[n["root"] for n in found[:3]]]
        ),
        "exhaustive": True,
    }
