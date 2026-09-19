"""Rijal and the transmission graph (Track I).

The corpus holds 34,178 narrations with parsed chains and, until this module,
analysed none of them. That is the largest gap between this tool and what a
hadith scholar actually does, and it is also where computation has the most to
add: an isnad corpus is a genuine graph with tens of thousands of nodes, and
questions that are laborious by hand — who is the bottleneck through which a
tradition passes, which narrator links two collections, where does a chain
thin to a single strand — are graph queries.

**What this module does not claim.** A narrator here is a *name*, obtained by
segmenting chains on the transmission particles. It is not a person. Two men
called Hammad ibn Salama are one node, and no amount of graph theory fixes
that; only biographical data does, and none is loaded. Rather than bury the
problem, :func:`conflation_report` measures it: a name that appears next to a
Companion in one chain and next to a ninth-century collector in another is
almost certainly several people, and the depth spread says so.

**Common links, with a null model.** Schacht and Juynboll argued that where the
chains of a tradition converge on one narrator, that narrator is where the
tradition enters the record. The argument is only as good as the alternative it
rules out, and the obvious alternative — that a prolific narrator shows up at
the neck of a small bundle because prolific narrators show up everywhere — is
rarely tested. :func:`common_link` tests it, by resampling chains from the
corpus-wide distribution and asking how often a bottleneck this tight arises
anyway.

Gradings are not computed. Reliability is not a property of a man; it is
something a named critic said in a named work, and those critics disagree.
:class:`~qra.models.NarratorGrading` requires both and ships empty.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from qra.analytics.isnad import is_relative_reference, narrators, split
from qra.arabic import search_form
from qra.models import (
    ChainPosition,
    Hadith,
    Narrator,
    NarratorGrading,
    TransmissionEdge,
)

# A chain shorter than this is usually a parsing failure rather than a short
# isnad — a mursal report still names someone.
MIN_CHAIN = 2
# Names longer than this are almost always a run of matn that the splitter kept.
MAX_NAME_WORDS = 6
# Resamples for the common-link null. 400 gives a resolution of 0.0025 on p.
TRIALS = 400
SEED = 20240617

GRADES = (
    "thiqa",
    "saduq",
    "maqbul",
    "layyin",
    "da'if",
    "matruk",
    "majhul",
    "kadhdhab",
)


class RijalError(ValueError):
    pass


@dataclass
class Chain:
    hadith_id: int
    collection: str
    # Narrator names, Prophet end first. A relative reference ("his father")
    # stays in the list, because it occupies a real position in the chain — it
    # simply cannot be resolved to a person.
    names: list[str]

    @property
    def unresolved(self) -> int:
        return sum(1 for n in self.names if is_relative_reference(n))


def _iqr(sorted_values: list[float]) -> float:
    """Interquartile range of an already-sorted list.

    The robust alternative to max - min, which a single unusual chain pins to
    1.0. At 2,500 appearances every major transmitter hits both extremes at
    least once, so max - min ranked them all identically suspect and said
    nothing.
    """
    n = len(sorted_values)
    if n < 4:
        return sorted_values[-1] - sorted_values[0]
    return sorted_values[(3 * n) // 4] - sorted_values[n // 4]


def _chain_of(hadith: Hadith) -> list[str]:
    """Names in one narration's chain, ordered from the Prophet outward.

    The stored text runs collector-first, which is how a chain is written. Depth
    is measured from the other end, because that is the end that is shared
    between collections and therefore the end that generations line up on.
    """
    if not hadith.text_ar:
        return []
    parsed = split(hadith.text_ar)
    names = [n for n in narrators(parsed.isnad) if n and len(n.split()) <= MAX_NAME_WORDS]
    return list(reversed(names))


def build(session: Session, *, limit: int | None = None) -> dict:
    """Extract every chain into narrators, positions and edges.

    Idempotent: the derived tables are rebuilt wholesale. They are a projection
    of the hadith corpus, and a projection that can drift from its source is
    worse than one that is recomputed.
    """
    # Gradings reference narrators, so a rebuild would orphan them. They ship
    # empty, but a deployment that has loaded a rijal source must not lose it.
    #
    # This check has to come before the first DELETE. It did not, and the guard
    # fired *after* wiping the chain positions and edges — refusing to do the
    # damage it had already done.
    graded = session.scalar(select(func.count()).select_from(NarratorGrading)) or 0
    if graded:
        raise RijalError(
            f"{graded} narrator gradings are stored. Rebuilding would orphan them; "
            "export them first, or clear them deliberately."
        )

    session.execute(delete(TransmissionEdge))
    session.execute(delete(ChainPosition))
    session.execute(delete(Narrator))
    session.commit()

    stmt = select(Hadith).where(Hadith.text_ar.is_not(None))
    if limit:
        stmt = stmt.limit(limit)

    chains: list[Chain] = []
    skipped = 0
    for hadith in session.scalars(stmt).yield_per(500):
        names = _chain_of(hadith)
        if len(names) < MIN_CHAIN:
            skipped += 1
            continue
        chains.append(Chain(hadith.id, hadith.collection, names))

    # --- narrators ---------------------------------------------------------
    surfaces: dict[str, Counter] = defaultdict(Counter)
    depths: dict[str, list[int]] = defaultdict(list)
    positions_seen: dict[str, list[float]] = defaultdict(list)
    for chain in chains:
        span = max(len(chain.names) - 1, 1)
        for depth, name in enumerate(chain.names):
            key = search_form(name)
            # "his father" is not a transmitter. Left in, it became the single
            # largest node in the graph — 3,488 narrations, as though one man
            # had taught a tenth of the corpus.
            if not key or is_relative_reference(name):
                continue
            surfaces[key][name] += 1
            depths[key].append(depth)
            positions_seen[key].append(depth / span)

    rows = []
    for key, counter in surfaces.items():
        seen = depths[key]
        rel = sorted(positions_seen[key])
        rows.append(
            {
                "canonical": key[:128],
                "display_name": counter.most_common(1)[0][0][:256],
                "variants": [v for v, _ in counter.most_common(8)],
                "narration_count": sum(counter.values()),
                "min_depth": min(seen),
                "max_depth": max(seen),
                "mean_depth": round(sum(seen) / len(seen), 3),
                "depth_spread": max(seen) - min(seen),
                "min_position": round(rel[0], 4),
                "max_position": round(rel[-1], 4),
                "mean_position": round(sum(rel) / len(rel), 4),
                "position_spread": round(_iqr(rel), 4),
                "provenance": "corpus_derived",
            }
        )
    session.execute(Narrator.__table__.insert(), rows)
    session.commit()

    ids = dict(session.execute(select(Narrator.canonical, Narrator.id)).all())

    # --- positions ---------------------------------------------------------
    positions = []
    for chain in chains:
        for depth, name in enumerate(chain.names):
            if is_relative_reference(name):
                continue
            narrator_id = ids.get(search_form(name)[:128])
            if narrator_id is None:
                continue
            positions.append(
                {
                    "hadith_id": chain.hadith_id,
                    "narrator_id": narrator_id,
                    "depth": depth,
                    "collection": chain.collection,
                }
            )
    # A chain can name the same person twice; the slot is unique on (hadith,
    # depth), so duplicates cannot arise, but a malformed parse can produce two
    # entries at one depth. Keep the first.
    seen_slots = set()
    deduped = []
    for row in positions:
        slot = (row["hadith_id"], row["depth"])
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        deduped.append(row)
    for start in range(0, len(deduped), 5000):
        session.execute(ChainPosition.__table__.insert(), deduped[start : start + 5000])
    session.commit()

    # --- edges -------------------------------------------------------------
    edges: dict[tuple[int, int], dict] = {}
    for chain in chains:
        # An unresolvable link *breaks* the chain rather than being skipped over.
        # Bridging it would assert that A transmitted to C when the text says A
        # transmitted to someone's father who transmitted to C — inventing an
        # edge that the source does not contain.
        chain_ids = [
            None if is_relative_reference(n) else ids.get(search_form(n)[:128])
            for n in chain.names
        ]
        for teacher, student in zip(chain_ids, chain_ids[1:], strict=False):
            if teacher is None or student is None or teacher == student:
                continue
            entry = edges.setdefault(
                (teacher, student),
                {"teacher_id": teacher, "student_id": student, "weight": 0, "collections": []},
            )
            entry["weight"] += 1
            if chain.collection not in entry["collections"]:
                entry["collections"].append(chain.collection)
    edge_rows = list(edges.values())
    for start in range(0, len(edge_rows), 5000):
        session.execute(TransmissionEdge.__table__.insert(), edge_rows[start : start + 5000])
    session.commit()

    invalidate()
    broken = sum(1 for c in chains if c.unresolved)
    return {
        "chains": len(chains),
        "skipped": skipped,
        "narrators": len(rows),
        "positions": len(deduped),
        "edges": len(edge_rows),
        "chains_with_unresolved_links": broken,
        "note": (
            f"{skipped:,} narrations yielded fewer than {MIN_CHAIN} names and were left out. "
            "A narrator row is a name, not a person — see conflation_report."
        ),
        "unresolved_note": (
            f"{broken:,} of {len(chains):,} chains ({broken / max(len(chains), 1):.0%}) contain a "
            "kinship reference such as عن أبيه that cannot be resolved without biographical "
            "data. Those chains are broken at that point rather than bridged, because bridging "
            "would assert a transmission the text does not contain."
        ),
    }


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def _edges(session: Session) -> tuple[dict[int, list[tuple[int, int]]], dict[int, list[tuple[int, int]]]]:
    """Adjacency in both directions: (teacher -> students), (student -> teachers)."""
    forward: dict[int, list[tuple[int, int]]] = defaultdict(list)
    backward: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for teacher, student, weight in session.execute(
        select(TransmissionEdge.teacher_id, TransmissionEdge.student_id, TransmissionEdge.weight)
    ).all():
        forward[teacher].append((student, weight))
        backward[student].append((teacher, weight))
    return forward, backward


def hubs(session: Session, *, limit: int = 25) -> dict:
    """The narrators the corpus flows through.

    Weighted degree, not betweenness. Betweenness on a graph this size is
    expensive and, more to the point, misleading here: an isnad graph is close
    to a DAG layered by generation, so betweenness mostly recovers the middle
    generations rather than saying anything about individuals.
    """
    forward, backward = _edges(session)
    names = dict(session.execute(select(Narrator.id, Narrator.display_name)).all())
    counts = dict(session.execute(select(Narrator.id, Narrator.narration_count)).all())

    scored = []
    for narrator_id, display in names.items():
        out_w = sum(w for _, w in forward.get(narrator_id, ()))
        in_w = sum(w for _, w in backward.get(narrator_id, ()))
        scored.append(
            {
                "narrator_id": narrator_id,
                "name": display,
                "students": len(forward.get(narrator_id, ())),
                "teachers": len(backward.get(narrator_id, ())),
                "transmitted_to": out_w,
                "received_from": in_w,
                "narrations": counts.get(narrator_id, 0),
            }
        )
    scored.sort(key=lambda row: -row["narrations"])
    return {
        "narrators_total": len(names),
        "edges_total": sum(len(v) for v in forward.values()),
        "hubs": scored[:limit],
        "measure": "weighted degree over the transmission graph",
        "caveat": (
            "A hub is a name that many chains pass through. Where that name is shared by "
            "several men the hub is an artefact of conflation rather than a fact about a "
            "transmitter — check it against conflation_report before reading anything into it."
        ),
    }


def conflation_report(session: Session, *, limit: int = 25, min_narrations: int = 20) -> dict:
    """Names that are probably more than one person.

    The diagnostic is *where in the chain* the name sits. Isnads are ordered by
    generation: a Companion stands at the Prophet end, the collector at the far
    end, and a given man occupies a narrow band between them. A name found both
    beside a Companion and beside a ninth-century collector is behaving like two
    men, because nobody transmits to his own great-great-grandchildren.

    Position is normalised per chain, 0.0 at the Prophet end and 1.0 at the
    collector. Raw depth cannot be compared across chains — an isnad of four
    links and one of twenty put their collector at depth 3 and depth 19 — so raw
    spread flags every collector as conflated and measures nothing but chain
    length.

    This is the number every name-based isnad study needs and almost none
    reports.
    """
    rows = session.execute(
        select(
            Narrator.id,
            Narrator.display_name,
            Narrator.narration_count,
            Narrator.min_position,
            Narrator.max_position,
            Narrator.mean_position,
            Narrator.position_spread,
        ).where(Narrator.narration_count >= min_narrations)
    ).all()
    if not rows:
        return {"examined": 0, "suspects": [], "reading": "the graph has not been built"}

    spreads = sorted(r.position_spread for r in rows)
    median = spreads[len(spreads) // 2]
    suspect = sorted(rows, key=lambda r: (-r.position_spread, -r.narration_count))

    return {
        "examined": len(rows),
        "median_position_spread": round(median, 4),
        "metric": (
            "interquartile range of chain position, normalised 0.0 (Prophet end) .. 1.0 "
            "(collector). The IQR rather than the full range, because one unusual chain "
            "pins max - min to 1.0 for every frequent name."
        ),
        "suspects": [
            {
                "narrator_id": r.id,
                "name": r.display_name,
                "narrations": r.narration_count,
                "position_range": [round(r.min_position, 3), round(r.max_position, 3)],
                "interquartile_spread": round(r.position_spread, 3),
                "position_spread": round(r.position_spread, 3),
                "mean_position": round(r.mean_position, 3),
            }
            for r in suspect[:limit]
        ],
        "reading": (
            f"The median name here spans {median:.2f} of the chain. Names spanning far more "
            "are behaving like several men sharing a spelling — سفيان is the textbook case, "
            "covering both al-Thawri and Ibn 'Uyayna. Nothing downstream should treat a "
            "high-spread node as an individual."
        ),
        "fix": (
            "Only biographical data resolves this. Load a rijal source with death years and "
            "teacher/student lists and the ambiguous nodes can be split."
        ),
    }


# ---------------------------------------------------------------------------
# Common links
# ---------------------------------------------------------------------------


def _chains_for(session: Session, hadith_ids: list[int]) -> dict[int, list[int]]:
    rows = session.execute(
        select(ChainPosition.hadith_id, ChainPosition.depth, ChainPosition.narrator_id)
        .where(ChainPosition.hadith_id.in_(hadith_ids))
        .order_by(ChainPosition.hadith_id, ChainPosition.depth)
    ).all()
    chains: dict[int, list[int]] = defaultdict(list)
    for hadith_id, _depth, narrator_id in rows:
        chains[hadith_id].append(narrator_id)
    return chains


def common_link(session: Session, hadith_ids: list[int], *, trials: int = TRIALS) -> dict:
    """The narrator a bundle of parallel chains converges on — tested.

    Juynboll's common link is the narrator through whom most or all chains of a
    tradition pass, and the claim built on it is that the tradition enters the
    record there. The claim is worth exactly as much as the alternative it
    excludes, and the alternative that matters is dull: a narrator who appears
    in thousands of chains will appear at the neck of a small bundle without any
    of it meaning anything.

    So the observed convergence is compared against bundles of the same size and
    shape assembled from the corpus at large. A common link that a random bundle
    reproduces half the time is not a finding.
    """
    if len(hadith_ids) < 3:
        raise RijalError(
            "a common link needs at least three independent chains; with fewer, "
            "convergence is arithmetic rather than evidence"
        )

    chains = _chains_for(session, hadith_ids)
    chains = {k: v for k, v in chains.items() if len(v) >= MIN_CHAIN}
    if len(chains) < 3:
        raise RijalError("fewer than three of those narrations have a usable chain")

    total = len(chains)
    appearances = Counter()
    for names in chains.values():
        for narrator_id in set(names):
            appearances[narrator_id] += 1

    # The common link is the narrator covering the most chains; ties break on
    # the one closest to the Prophet end, which is the earlier claim.
    depth_of: dict[int, float] = defaultdict(float)
    counts: Counter = Counter()
    for names in chains.values():
        for depth, narrator_id in enumerate(names):
            depth_of[narrator_id] += depth
            counts[narrator_id] += 1
    mean_depth = {k: depth_of[k] / counts[k] for k in counts}

    ranked = sorted(
        appearances.items(), key=lambda kv: (-kv[1], mean_depth.get(kv[0], 99))
    )
    best_id, coverage = ranked[0]
    share = coverage / total

    # --- the null ---------------------------------------------------------
    # Resample bundles of the same size from the whole corpus, preserving chain
    # length, and see how often *some* narrator covers this share.
    all_chains = _corpus_chains(session)
    rng = random.Random(SEED)
    lengths = [len(v) for v in chains.values()]
    by_length: dict[int, list[list[int]]] = defaultdict(list)
    for chain in all_chains:
        by_length[len(chain)].append(chain)
    usable_lengths = [n for n in lengths if by_length.get(n)]

    at_least = 0
    null_shares = []
    if usable_lengths:
        for _ in range(trials):
            sample = [rng.choice(by_length[n]) for n in usable_lengths]
            seen = Counter()
            for chain in sample:
                for narrator_id in set(chain):
                    seen[narrator_id] += 1
            top = max(seen.values()) / len(sample) if sample else 0.0
            null_shares.append(top)
            if top >= share:
                at_least += 1

    p_value = (at_least + 1) / (trials + 1) if usable_lengths else None
    null_mean = sum(null_shares) / len(null_shares) if null_shares else None

    names = dict(session.execute(select(Narrator.id, Narrator.display_name)).all())
    spread = dict(session.execute(select(Narrator.id, Narrator.position_spread)).all())

    return {
        "chains_examined": total,
        "common_link": {
            "narrator_id": best_id,
            "name": names.get(best_id, "?"),
            "chains_covered": coverage,
            "share": round(share, 4),
            "mean_depth": round(mean_depth.get(best_id, 0.0), 2),
            "depth_spread": spread.get(best_id, 0.0),
        },
        "partial_common_links": [
            {
                "narrator_id": nid,
                "name": names.get(nid, "?"),
                "chains_covered": cov,
                "share": round(cov / total, 4),
                "mean_depth": round(mean_depth.get(nid, 0.0), 2),
            }
            for nid, cov in ranked[1:6]
            if cov >= max(2, total * 0.3)
        ],
        "null_model": {
            "trials": trials,
            "mean_top_share": round(null_mean, 4) if null_mean is not None else None,
            "p_value": round(p_value, 4) if p_value is not None else None,
            "method": (
                "bundles of the same size and chain-length profile resampled from the whole "
                "corpus; the statistic is the top narrator's coverage share. Add-one, so a "
                "finite resample never reports zero."
            ),
        },
        "beyond_chance": bool(p_value is not None and p_value < 0.05),
        "reading": _common_link_reading(share, p_value, spread.get(best_id, 0.0)),
        "provenance": "system_suggested",
    }


def _common_link_reading(share: float, p_value: float | None, position_spread: float) -> str:
    if p_value is None:
        return (
            "No comparable bundles exist in the corpus, so the convergence cannot be tested. "
            "An untested common link is a description of this bundle, not evidence about it."
        )
    if p_value >= 0.05:
        return (
            f"This narrator covers {share:.0%} of the chains, and bundles assembled at random "
            "from the corpus reach that often enough that the convergence carries no weight. "
            "This is the usual fate of a common link found in a small bundle around a prolific "
            "transmitter."
        )
    warning = (
        " Note that this name spans a wide range of chain depths, so it may be several men "
        "rather than one — which would dissolve the bottleneck entirely."
        if position_spread >= 0.6
        else ""
    )
    return (
        f"This narrator covers {share:.0%} of the chains, tighter than resampled bundles of the "
        "same shape reach. That is a real bottleneck and the place to look for where the "
        "tradition enters the written record — it is not, on its own, a date or an attribution."
        + warning
    )


_CORPUS_CHAINS: list[list[int]] | None = None


def _corpus_chains(session: Session) -> list[list[int]]:
    """Every chain in the corpus, for the null model.

    Cached per process: this is a 163k-row scan and the null resamples from it
    on every common-link call, which put 16 seconds on each one.
    """
    global _CORPUS_CHAINS
    if _CORPUS_CHAINS is not None:
        return _CORPUS_CHAINS
    rows = session.execute(
        select(ChainPosition.hadith_id, ChainPosition.narrator_id)
        .order_by(ChainPosition.hadith_id, ChainPosition.depth)
    ).all()
    chains: dict[int, list[int]] = defaultdict(list)
    for hadith_id, narrator_id in rows:
        chains[hadith_id].append(narrator_id)
    _CORPUS_CHAINS = [v for v in chains.values() if len(v) >= MIN_CHAIN]
    return _CORPUS_CHAINS


def invalidate() -> None:
    """Drop the cached corpus scan — after a rebuild, and in tests."""
    global _CORPUS_CHAINS
    _CORPUS_CHAINS = None


def narrator(session: Session, narrator_id: int, *, limit: int = 20) -> dict:
    """One name: where it sits, who it received from, who received from it."""
    row = session.get(Narrator, narrator_id)
    if row is None:
        raise RijalError(f"no narrator {narrator_id}")

    teachers = session.execute(
        select(Narrator.display_name, TransmissionEdge.weight, TransmissionEdge.collections)
        .join(Narrator, Narrator.id == TransmissionEdge.teacher_id)
        .where(TransmissionEdge.student_id == narrator_id)
        .order_by(TransmissionEdge.weight.desc())
        .limit(limit)
    ).all()
    students = session.execute(
        select(Narrator.display_name, TransmissionEdge.weight, TransmissionEdge.collections)
        .join(Narrator, Narrator.id == TransmissionEdge.student_id)
        .where(TransmissionEdge.teacher_id == narrator_id)
        .order_by(TransmissionEdge.weight.desc())
        .limit(limit)
    ).all()
    by_collection = dict(
        session.execute(
            select(ChainPosition.collection, func.count())
            .where(ChainPosition.narrator_id == narrator_id)
            .group_by(ChainPosition.collection)
        ).all()
    )
    gradings = session.scalars(
        select(NarratorGrading).where(NarratorGrading.narrator_id == narrator_id)
    ).all()

    return {
        "id": row.id,
        "name": row.display_name,
        "variants": row.variants or [],
        "narrations": row.narration_count,
        "depth_range": [row.min_depth, row.max_depth],
        "depth_spread": row.depth_spread,
        "mean_depth": row.mean_depth,
        "by_collection": by_collection,
        "received_from": [
            {"name": n, "narrations": w, "collections": c} for n, w, c in teachers
        ],
        "transmitted_to": [
            {"name": n, "narrations": w, "collections": c} for n, w, c in students
        ],
        "gradings": [
            {
                "grade": g.grade,
                "critic": g.critic,
                "source_work": g.source_work,
                "reasoning": g.reasoning,
            }
            for g in gradings
        ],
        "grading_note": (
            "No grading is on record for this name. Reliability is not computed here — it is "
            "something a named critic said in a named work, and the critics disagree."
            if not gradings
            else "Each grading names the critic who gave it. Where they differ, they differ."
        ),
        # The single most important caveat in the module.
        "position_range": [row.min_position, row.max_position],
        "position_spread": row.position_spread,
        # The decision and the number shown must be the same number. Reporting
        # the full 0.00–1.00 range and then concluding "consistent with one man"
        # from the interquartile spread reads as a contradiction.
        "identity_warning": (
            f"This is a name, not a person. Across the chains it appears in, the middle half "
            f"of its positions span {row.position_spread:.2f} of the chain, where 0 is the "
            "Prophet end and 1 the collector"
            + (
                " — wide enough that this is very likely several men sharing a spelling."
                if row.position_spread >= 0.4
                else ", which is consistent with one man."
            )
            + f" Full observed range: {row.min_position:.2f} to {row.max_position:.2f}."
        ),
        "provenance": row.provenance,
    }


def record_grading(
    session: Session,
    narrator_id: int,
    *,
    grade: str,
    critic: str,
    source_work: str,
    reasoning: str = "",
    notes: str | None = None,
) -> dict:
    """Store one critic's verdict. Every field that carries authority is required."""
    if session.get(Narrator, narrator_id) is None:
        raise RijalError(f"no narrator {narrator_id}")
    if grade not in GRADES:
        raise RijalError(f"grade must be one of {', '.join(GRADES)}")
    if not (critic or "").strip():
        raise RijalError(
            "name the critic. A narrator is not reliable or unreliable in the abstract; "
            "someone said so, and this table exists so that it cannot be stored otherwise."
        )
    if not (source_work or "").strip():
        raise RijalError("name the work the grading appears in")

    row = NarratorGrading(
        narrator_id=narrator_id,
        grade=grade,
        critic=critic.strip(),
        source_work=source_work.strip(),
        reasoning=reasoning,
        notes=notes,
    )
    session.add(row)
    session.commit()
    return {"recorded": True, "narrator_id": narrator_id, "grade": grade, "critic": row.critic}


def summary(session: Session) -> dict:
    narrators_total = session.scalar(select(func.count()).select_from(Narrator)) or 0
    return {
        "narrators": narrators_total,
        "chain_positions": session.scalar(select(func.count()).select_from(ChainPosition)) or 0,
        "edges": session.scalar(select(func.count()).select_from(TransmissionEdge)) or 0,
        "gradings": session.scalar(select(func.count()).select_from(NarratorGrading)) or 0,
        "built": narrators_total > 0,
        "note": (
            "Run `qra rijal build` to project the hadith corpus into the transmission graph."
            if not narrators_total
            else "Nodes are names. See /hadith/rijal/conflation before treating one as a person."
        ),
    }
