"""Conditional-structure mining: إِنْ / إِذَا … فَ… as condition -> consequence.

If the Qur'an states laws governing human behaviour, its conditional
constructions are where those laws are stated in a form you can actually test:
``condition -> consequence`` is a claim with a subject, a trigger and an
outcome. This module queries the triples mined at ingest
(:func:`qra.ingest.indexes.mine_conditionals`) and aggregates them into
patterns: which roots appear in protases, which in apodoses, and which pairs
recur.

Confidence is always exposed. A structure with an explicit فَ carries the
annotators' judgement about where the apodosis starts (0.9); one without it was
split by our stated heuristic (0.5) and should be read individually.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.arabic import normalise_root
from qra.citations import ayah_citation
from qra.models import Ayah, ConditionalStructure, Root


def _row_payload(session: Session, row: ConditionalStructure, ayah: Ayah) -> dict:
    return {
        "id": row.id,
        "ayah_id": row.ayah_id,
        "ref": f"{ayah.surah_id}:{ayah.ayah_num}",
        "particle": row.particle,
        "particle_form": row.particle_form,
        "condition": row.condition_text,
        "consequence": row.consequence_text,
        "condition_roots": row.condition_roots,
        "consequence_roots": row.consequence_roots,
        "explicit_apodosis": bool(row.apodosis_marker),
        "confidence": row.confidence,
        "revelation_place": ayah.revelation_place,
        "revelation_order": ayah.revelation_order,
        "citation": ayah_citation(ayah).to_dict(),
    }


def find_conditionals(
    session: Session,
    *,
    roots: list[str] | None = None,
    particle: str | None = None,
    revelation_place: str | None = None,
    min_confidence: float = 0.0,
    role: str | None = None,  # condition | consequence | both
    limit: int = 100,
) -> dict:
    """Search mined conditionals, optionally by the roots they involve."""
    corpus_total = session.scalar(select(func.count()).select_from(ConditionalStructure)) or 0

    stmt = (
        select(ConditionalStructure, Ayah)
        .join(Ayah, Ayah.id == ConditionalStructure.ayah_id)
        .where(ConditionalStructure.confidence >= min_confidence)
    )
    if particle:
        stmt = stmt.where(ConditionalStructure.particle == particle)
    if revelation_place:
        stmt = stmt.where(Ayah.revelation_place == revelation_place)

    wanted: set[str] = set()
    if roots:
        keys = [normalise_root(r) for r in roots]
        wanted = {
            display
            for (display,) in session.execute(
                select(Root.root_display).where(Root.root.in_(keys))
            ).all()
        }

    results = []
    for row, ayah in session.execute(stmt.order_by(ConditionalStructure.ayah_id)).all():
        in_condition = bool(wanted & set(row.condition_roots)) if wanted else True
        in_consequence = bool(wanted & set(row.consequence_roots)) if wanted else True
        if wanted and not (in_condition or in_consequence):
            continue
        if wanted:
            row_role = "both" if in_condition and in_consequence else (
                "condition" if in_condition else "consequence"
            )
        else:
            row_role = "any"
        if role and row_role not in (role, "both"):
            continue
        payload = _row_payload(session, row, ayah)
        payload["role"] = row_role
        results.append(payload)

    return {
        "total": len(results),
        "corpus_total": corpus_total,
        "roots": sorted(wanted) if wanted else None,
        "results": results[:limit],
        "truncated": len(results) > limit,
    }


def particle_summary(session: Session) -> dict:
    rows = session.execute(
        select(
            ConditionalStructure.particle,
            func.count(),
            func.count(ConditionalStructure.apodosis_marker),
        ).group_by(ConditionalStructure.particle)
    ).all()
    by_place = dict(
        session.execute(
            select(Ayah.revelation_place, func.count())
            .join(ConditionalStructure, ConditionalStructure.ayah_id == Ayah.id)
            .group_by(Ayah.revelation_place)
        ).all()
    )
    return {
        "particles": [
            {"particle": particle, "count": n, "with_explicit_fa": int(explicit or 0)}
            for particle, n, explicit in sorted(rows, key=lambda r: -r[1])
        ],
        "by_revelation_place": by_place,
        "total": sum(n for _p, n, _e in rows),
    }


def condition_consequence_patterns(
    session: Session, *, min_count: int = 3, top: int = 40, min_confidence: float = 0.5
) -> dict:
    """Recurring root pairs across the protasis/apodosis boundary.

    "When <root in condition>, then <root in consequence>" — the aggregate view
    of the corpus's conditional logic. Pairs are counted, not scored against a
    baseline, because the sample per pair is small; the count is the finding and
    is presented as such.
    """
    rows = session.scalars(
        select(ConditionalStructure).where(ConditionalStructure.confidence >= min_confidence)
    ).all()

    pairs: Counter[tuple[str, str]] = Counter()
    condition_roots: Counter[str] = Counter()
    consequence_roots: Counter[str] = Counter()
    examples: dict[tuple[str, str], list[int]] = {}

    for row in rows:
        condition_roots.update(row.condition_roots)
        consequence_roots.update(row.consequence_roots)
        for a in row.condition_roots:
            for b in row.consequence_roots:
                if a == b:
                    continue
                pairs[(a, b)] += 1
                examples.setdefault((a, b), []).append(row.id)

    return {
        "structures_considered": len(rows),
        "min_confidence": min_confidence,
        "top_condition_roots": [{"root": r, "count": n} for r, n in condition_roots.most_common(20)],
        "top_consequence_roots": [
            {"root": r, "count": n} for r, n in consequence_roots.most_common(20)
        ],
        "pairs": [
            {
                "condition_root": a,
                "consequence_root": b,
                "count": n,
                "example_structure_ids": examples[(a, b)][:5],
            }
            for (a, b), n in pairs.most_common(top)
            if n >= min_count
        ],
        "note": (
            "Counts only. A recurring pair is a lead to read, not a demonstrated law — "
            "the roots in a protasis are dominated by high-frequency vocabulary."
        ),
    }


def get_conditional(session: Session, structure_id: int) -> dict:
    row = session.get(ConditionalStructure, structure_id)
    if row is None:
        return {}
    ayah = session.get(Ayah, row.ayah_id)
    payload = _row_payload(session, row, ayah)
    payload["full_ayah"] = ayah.text_uthmani
    return payload
