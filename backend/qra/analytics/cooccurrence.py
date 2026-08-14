"""Co-occurrence and PMI: which roots cluster together beyond chance.

Scope matters and is always reported. Two roots that never share an ayah but
constantly share a ruku are making a compositional claim; two that share the
same ayah are making a lexical one. The default scope is the ayah; ruku and
surah are available because passage-level association is often the real
phenomenon.

Every association is reported with its expected value under independence and a
significance test, and any ranked sweep is corrected for multiple comparisons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from qra.analytics.stats import Significance, assess, correct_multiple, sweep_warning
from qra.arabic import normalise_root
from qra.models import Ayah, Root

SCOPES = {
    "ayah": "s.ayah_id",
    "ruku": "(ay.surah_id * 1000 + ay.ruku)",
    "surah": "ay.surah_id",
}


@dataclass
class Association:
    root_a: str
    root_b: str
    scope: str
    units_a: int
    units_b: int
    units_both: int
    units_total: int
    pmi: float
    npmi: float
    jaccard: float
    expected_both: float
    significance: Significance

    def to_dict(self) -> dict:
        return {
            "root_a": self.root_a,
            "root_b": self.root_b,
            "scope": self.scope,
            "units_with_a": self.units_a,
            "units_with_b": self.units_b,
            "units_with_both": self.units_both,
            "units_total": self.units_total,
            "expected_both": round(self.expected_both, 2),
            "pmi": round(self.pmi, 3),
            "npmi": round(self.npmi, 3),
            "jaccard": round(self.jaccard, 4),
            "significance": self.significance.to_dict(),
        }


def _unit_expr(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {sorted(SCOPES)}")
    return SCOPES[scope]


def _total_units(session: Session, scope: str) -> int:
    if scope == "ayah":
        return session.scalar(select(func.count()).select_from(Ayah)) or 0
    if scope == "surah":
        return session.scalar(select(func.count(func.distinct(Ayah.surah_id)))) or 0
    return session.scalar(
        select(func.count(func.distinct(Ayah.surah_id * 1000 + Ayah.ruku)))
    ) or 0


def _units_for_root(session: Session, root_id: int, scope: str) -> set[int]:
    expr = _unit_expr(scope)
    rows = session.execute(
        sql_text(
            f"""
            select distinct {expr} as unit
            from segment s join ayah ay on ay.id = s.ayah_id
            where s.root_id = :rid
            """
        ),
        {"rid": root_id},
    ).all()
    return {int(r[0]) for r in rows}


def associate(session: Session, root_a: str, root_b: str, *, scope: str = "ayah") -> dict:
    """PMI and significance for one root pair at one scope."""
    keys = [normalise_root(root_a), normalise_root(root_b)]
    rows = {r.root: r for r in session.scalars(select(Root).where(Root.root.in_(keys))).all()}
    if len(rows) != 2:
        return {"found": False, "missing": [k for k in keys if k not in rows]}

    a, b = rows[keys[0]], rows[keys[1]]
    total = _total_units(session, scope)
    units_a = _units_for_root(session, a.id, scope)
    units_b = _units_for_root(session, b.id, scope)
    both = units_a & units_b

    p_a = len(units_a) / total if total else 0.0
    p_b = len(units_b) / total if total else 0.0
    p_ab = len(both) / total if total else 0.0
    expected = p_a * p_b * total

    if p_ab > 0 and p_a > 0 and p_b > 0:
        pmi = math.log2(p_ab / (p_a * p_b))
        npmi = pmi / (-math.log2(p_ab))
    else:
        pmi = float("-inf")
        npmi = -1.0

    # Null model: B is distributed independently of A across units.
    significance = assess(
        len(both),
        len(units_a),
        p_b,
        label=f"{a.root_display}+{b.root_display} co-occurrence per {scope}",
    )

    association = Association(
        root_a=a.root_display,
        root_b=b.root_display,
        scope=scope,
        units_a=len(units_a),
        units_b=len(units_b),
        units_both=len(both),
        units_total=total,
        pmi=pmi,
        npmi=npmi,
        jaccard=len(both) / len(units_a | units_b) if (units_a | units_b) else 0.0,
        expected_both=expected,
        significance=significance,
    )
    payload = association.to_dict()
    payload["found"] = True
    payload["shared_units"] = sorted(both)[:200]
    return payload


def top_partners(
    session: Session,
    root: str,
    *,
    scope: str = "ayah",
    min_shared: int = 3,
    limit: int = 25,
    min_partner_occurrences: int = 5,
) -> dict:
    """Rank a root's strongest associations, corrected across the whole sweep."""
    key = normalise_root(root)
    row = session.scalar(select(Root).where(Root.root == key))
    if row is None:
        return {"found": False, "root": key}

    expr = _unit_expr(scope)
    total = _total_units(session, scope)
    units_a = _units_for_root(session, row.id, scope)
    if not units_a:
        return {"found": False, "root": key}

    rows = session.execute(
        sql_text(
            f"""
            with a_units as (
                select distinct {expr} as unit
                from segment s join ayah ay on ay.id = s.ayah_id
                where s.root_id = :rid
            ),
            partner as (
                select s.root_id, {expr} as unit
                from segment s join ayah ay on ay.id = s.ayah_id
                where s.root_id is not null and s.root_id <> :rid
                group by s.root_id, unit
            )
            select r.root_display, r.id,
                   count(distinct p.unit) filter (where p.unit in (select unit from a_units)) as shared,
                   count(distinct p.unit) as total_units
            from partner p join root r on r.id = p.root_id
            group by r.root_display, r.id
            having count(distinct p.unit) filter (where p.unit in (select unit from a_units)) >= :min_shared
               and count(distinct p.unit) >= :min_partner
            """
        ),
        {"rid": row.id, "min_shared": min_shared, "min_partner": min_partner_occurrences},
    ).all()

    associations: list[Association] = []
    significances: list[Significance] = []
    for display, _rid, shared, partner_units in rows:
        p_a = len(units_a) / total
        p_b = partner_units / total
        p_ab = shared / total
        pmi = math.log2(p_ab / (p_a * p_b)) if p_ab > 0 else float("-inf")
        npmi = pmi / (-math.log2(p_ab)) if p_ab > 0 else -1.0
        significance = assess(
            shared, len(units_a), p_b, label=f"{row.root_display}+{display} per {scope}"
        )
        significances.append(significance)
        associations.append(
            Association(
                root_a=row.root_display,
                root_b=display,
                scope=scope,
                units_a=len(units_a),
                units_b=partner_units,
                units_both=shared,
                units_total=total,
                pmi=pmi,
                npmi=npmi,
                jaccard=shared / (len(units_a) + partner_units - shared),
                expected_both=p_a * p_b * total,
                significance=significance,
            )
        )

    correct_multiple(significances)
    ranked = sorted(associations, key=lambda a: (a.significance.corrected_p or 1.0, -a.npmi))

    return {
        "found": True,
        "root": row.root_display,
        "scope": scope,
        "units_total": total,
        "units_with_root": len(units_a),
        "tested_partners": len(associations),
        "surviving_correction": sum(1 for a in associations if not a.significance.within_chance),
        "sweep_warning": sweep_warning(len(associations)),
        "partners": [a.to_dict() for a in ranked[:limit]],
    }


def cluster_map(
    session: Session, roots: list[str], *, scope: str = "ayah", min_shared: int = 2
) -> dict:
    """Pairwise association matrix for a chosen set of roots.

    Bounded to a set the researcher names, because an all-pairs sweep over 1,651
    roots is 1.4M tests — computable, but a machine for generating false
    findings.
    """
    keys = [normalise_root(r) for r in roots]
    rows = {r.root: r for r in session.scalars(select(Root).where(Root.root.in_(keys))).all()}
    found = [rows[k] for k in keys if k in rows]
    total = _total_units(session, scope)
    units = {r.id: _units_for_root(session, r.id, scope) for r in found}

    edges = []
    significances = []
    for i, a in enumerate(found):
        for b in found[i + 1 :]:
            shared = units[a.id] & units[b.id]
            if len(shared) < min_shared:
                continue
            p_a = len(units[a.id]) / total
            p_b = len(units[b.id]) / total
            p_ab = len(shared) / total
            pmi = math.log2(p_ab / (p_a * p_b)) if p_ab else float("-inf")
            significance = assess(
                len(shared), len(units[a.id]), p_b, label=f"{a.root_display}+{b.root_display}"
            )
            significances.append(significance)
            edges.append(
                {
                    "source": a.root_display,
                    "target": b.root_display,
                    "shared": len(shared),
                    "expected": round(p_a * p_b * total, 2),
                    "pmi": round(pmi, 3),
                    "significance": significance,
                }
            )
    correct_multiple(significances)
    for edge in edges:
        edge["significance"] = edge["significance"].to_dict()

    return {
        "scope": scope,
        "units_total": total,
        "nodes": [
            {"root": r.root_display, "units": len(units[r.id]), "occurrences": r.occurrence_count}
            for r in found
        ],
        "edges": sorted(edges, key=lambda e: -e["pmi"]),
        "missing": [k for k in keys if k not in rows],
        "sweep_warning": sweep_warning(len(edges)),
    }
