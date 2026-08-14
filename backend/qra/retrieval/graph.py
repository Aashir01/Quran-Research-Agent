"""Graph traversal: ayah -> root -> co-occurring ayat -> concept -> tafsir/hadith.

Postgres recursive CTEs and joins, not a separate graph store. The whole edge
set is small (≈130k segment->root edges, a few thousand concept and link rows);
Neo4j would be a dependency without a payoff until traversals get much deeper.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from qra.arabic import normalise_root
from qra.citations import ayah_citation, hadith_citation, tafsir_citation
from qra.models import (
    Ayah,
    AyahLink,
    Concept,
    ConceptAyah,
    ConceptRoot,
    Edition,
    Hadith,
    HadithAyahLink,
    Root,
    Segment,
    TafsirEntry,
)
from qra.retrieval.base import Span


def ayah_neighbourhood(session: Session, ayah_id: int, *, depth: int = 1, limit: int = 25) -> dict:
    """Everything one or two hops from an ayah, with the path that got there."""
    ayah = session.get(Ayah, ayah_id)
    if ayah is None:
        return {}

    roots = session.execute(
        select(Root.id, Root.root_display, Root.occurrence_count, func.count(Segment.id))
        .join(Segment, Segment.root_id == Root.id)
        .where(Segment.ayah_id == ayah_id)
        .group_by(Root.id, Root.root_display, Root.occurrence_count)
        .order_by(func.count(Segment.id).desc())
    ).all()

    concepts = session.execute(
        select(Concept.slug, Concept.label_en, ConceptAyah.weight, ConceptAyah.provenance)
        .join(ConceptAyah, ConceptAyah.concept_id == Concept.id)
        .where(ConceptAyah.ayah_id == ayah_id)
        .order_by(ConceptAyah.weight.desc())
    ).all()

    similar = session.execute(
        select(AyahLink.dst_ayah_id, AyahLink.kind, AyahLink.score, AyahLink.detail, Ayah)
        .join(Ayah, Ayah.id == AyahLink.dst_ayah_id)
        .where(AyahLink.src_ayah_id == ayah_id)
        .order_by(AyahLink.score.desc())
        .limit(limit)
    ).all()

    hadith = session.execute(
        select(Hadith, Edition, HadithAyahLink.evidence)
        .join(HadithAyahLink, HadithAyahLink.hadith_id == Hadith.id)
        .join(Edition, Edition.id == Hadith.edition_id)
        .where(HadithAyahLink.ayah_id == ayah_id)
        .limit(limit)
    ).all()

    tafsir = session.execute(
        select(TafsirEntry, Edition)
        .join(Edition, Edition.id == TafsirEntry.edition_id)
        .where(
            TafsirEntry.surah_id == ayah.surah_id,
            TafsirEntry.ayah_start <= ayah.ayah_num,
            TafsirEntry.ayah_end >= ayah.ayah_num,
        )
    ).all()

    return {
        "ayah": {
            "id": ayah.id,
            "ref": f"{ayah.surah_id}:{ayah.ayah_num}",
            "text": ayah.text_uthmani,
            "citation": ayah_citation(ayah).to_dict(),
        },
        "roots": [
            {
                "root": display,
                "in_ayah": n,
                "corpus_occurrences": total,
                "path": ["ayah", "root"],
            }
            for _rid, display, total, n in roots
        ],
        "concepts": [
            {"slug": slug, "label": label, "weight": weight, "provenance": provenance, "path": ["ayah", "concept"]}
            for slug, label, weight, provenance in concepts
        ],
        "related_ayat": [
            {
                "ayah_id": dst,
                "ref": f"{row.surah_id}:{row.ayah_num}",
                "text": row.text_uthmani,
                "kind": kind,
                "score": round(score, 3),
                "delta": detail.get("delta_b") if isinstance(detail, dict) else None,
                "path": ["ayah", kind, "ayah"],
                "citation": ayah_citation(row).to_dict(),
            }
            for dst, kind, score, detail, row in similar
        ],
        "hadith": [
            {
                "text": h.text_ar,
                "translation": h.text_translation,
                "grading": h.grading,
                "evidence": evidence,
                "citation": hadith_citation(h, e).to_dict(),
                "path": ["ayah", "quoted_by", "hadith"],
            }
            for h, e, evidence in hadith
        ],
        "tafsir": [
            {
                "edition": e.slug,
                "author": e.author,
                "era": e.era,
                "excerpt": t.text[:600],
                "citation": tafsir_citation(t, e).to_dict(),
                "path": ["ayah", "commented_on_by", "tafsir"],
            }
            for t, e in tafsir
        ],
        "depth": depth,
    }


def cooccurring_ayat(
    session: Session, root: str, *, partner_root: str | None = None, limit: int = 50
) -> list[Span]:
    """Ayat containing a root, optionally restricted to those with a second root."""
    key = normalise_root(root)
    root_row = session.scalar(select(Root).where(Root.root == key))
    if root_row is None:
        return []

    stmt = select(Ayah).join(Segment, Segment.ayah_id == Ayah.id).where(Segment.root_id == root_row.id)
    if partner_root:
        partner = session.scalar(select(Root).where(Root.root == normalise_root(partner_root)))
        if partner is None:
            return []
        partner_ayat = select(Segment.ayah_id).where(Segment.root_id == partner.id)
        stmt = stmt.where(Ayah.id.in_(partner_ayat))
    rows = session.scalars(stmt.distinct().order_by(Ayah.id).limit(limit)).all()
    return [
        Span(
            kind="ayah",
            text=row.text_uthmani,
            citation=ayah_citation(row),
            ayah_id=row.id,
            ref=f"{row.surah_id}:{row.ayah_num}",
            retrieval_mode="graph",
            extra={"roots": [root, partner_root] if partner_root else [root]},
        )
        for row in rows
    ]


def concept_expansion(session: Session, slug: str, *, limit: int = 100) -> dict:
    """From a concept to its roots to every ayah that carries one."""
    concept = session.scalar(select(Concept).where(Concept.slug == slug))
    if concept is None:
        return {}
    roots = session.execute(
        select(Root.root_display, Root.occurrence_count)
        .join(ConceptRoot, ConceptRoot.root_id == Root.id)
        .where(ConceptRoot.concept_id == concept.id)
    ).all()
    ayat = session.execute(
        select(Ayah, ConceptAyah.weight)
        .join(ConceptAyah, ConceptAyah.ayah_id == Ayah.id)
        .where(ConceptAyah.concept_id == concept.id)
        .order_by(ConceptAyah.weight.desc(), Ayah.id)
        .limit(limit)
    ).all()
    total = session.scalar(
        select(func.count()).select_from(ConceptAyah).where(ConceptAyah.concept_id == concept.id)
    )
    return {
        "concept": {"slug": concept.slug, "label_en": concept.label_en, "label_ur": concept.label_ur},
        "roots": [{"root": r, "occurrences": n} for r, n in roots],
        "total_ayat": total,
        "provenance": "derived",
        "note": "Concept membership is derived from root membership, not asserted by a scholar.",
        "ayat": [
            {
                "ayah_id": ayah.id,
                "ref": f"{ayah.surah_id}:{ayah.ayah_num}",
                "text": ayah.text_uthmani,
                "weight": weight,
                "citation": ayah_citation(ayah).to_dict(),
            }
            for ayah, weight in ayat
        ],
    }


def root_bridges(session: Session, root_a: str, root_b: str, *, limit: int = 50) -> dict:
    """Where two roots meet: shared ayat, shared rukus, shared surahs.

    The three scopes matter — roots that never share an ayah but always share a
    ruku are making a different kind of claim from roots that co-occur inside a
    single verse.
    """
    keys = [normalise_root(root_a), normalise_root(root_b)]
    rows = {r.root: r for r in session.scalars(select(Root).where(Root.root.in_(keys))).all()}
    if len(rows) != 2:
        return {"found": False, "missing": [k for k in keys if k not in rows]}

    a, b = rows[keys[0]], rows[keys[1]]
    ayat_a = select(Segment.ayah_id).where(Segment.root_id == a.id).distinct()
    ayat_b = select(Segment.ayah_id).where(Segment.root_id == b.id).distinct()

    shared_ayat = session.scalars(
        select(Ayah.id).where(Ayah.id.in_(ayat_a), Ayah.id.in_(ayat_b)).order_by(Ayah.id)
    ).all()

    rukus = session.execute(
        sql_text(
            """
            with a as (select distinct ay.surah_id, ay.ruku from segment s
                       join ayah ay on ay.id = s.ayah_id where s.root_id = :a),
                 b as (select distinct ay.surah_id, ay.ruku from segment s
                       join ayah ay on ay.id = s.ayah_id where s.root_id = :b)
            select a.surah_id, a.ruku from a join b using (surah_id, ruku)
            order by a.surah_id, a.ruku
            """
        ),
        {"a": a.id, "b": b.id},
    ).all()

    surahs_a = {s for (s,) in session.execute(select(Segment.surah_id).where(Segment.root_id == a.id).distinct())}
    surahs_b = {s for (s,) in session.execute(select(Segment.surah_id).where(Segment.root_id == b.id).distinct())}

    return {
        "found": True,
        "root_a": {"root": a.root_display, "occurrences": a.occurrence_count, "ayat": a.ayah_count},
        "root_b": {"root": b.root_display, "occurrences": b.occurrence_count, "ayat": b.ayah_count},
        "shared_ayat": shared_ayat[:limit],
        "shared_ayat_count": len(shared_ayat),
        "shared_ruku_count": len(rukus),
        "shared_surahs": sorted(surahs_a & surahs_b),
        "only_in_a_surahs": sorted(surahs_a - surahs_b),
        "only_in_b_surahs": sorted(surahs_b - surahs_a),
    }


def root_family_graph(session: Session, root: str, *, top_partners: int = 20) -> dict:
    """One-hop neighbourhood of a root: the roots it keeps company with."""
    key = normalise_root(root)
    row = session.scalar(select(Root).where(Root.root == key))
    if row is None:
        return {}
    partners = session.execute(
        sql_text(
            """
            select r2.root_display, count(distinct s2.ayah_id) as shared
            from segment s1
            join segment s2 on s2.ayah_id = s1.ayah_id and s2.root_id <> s1.root_id
            join root r2 on r2.id = s2.root_id
            where s1.root_id = :rid
            group by r2.root_display
            order by shared desc
            limit :lim
            """
        ),
        {"rid": row.id, "lim": top_partners},
    ).all()
    return {
        "root": row.root_display,
        "occurrences": row.occurrence_count,
        "ayat": row.ayah_count,
        "partners": [{"root": r, "shared_ayat": n} for r, n in partners],
        "note": "Raw shared-ayah counts. Use /analytics/cooccurrence for PMI with a chance baseline.",
    }


def surah_root_profile(session: Session, surah_id: int, *, top: int = 30) -> dict:
    rows = session.execute(
        select(Root.root_display, func.count(Segment.id))
        .join(Segment, Segment.root_id == Root.id)
        .where(Segment.surah_id == surah_id)
        .group_by(Root.root_display)
        .order_by(func.count(Segment.id).desc())
        .limit(top)
    ).all()
    return {"surah": surah_id, "roots": [{"root": r, "count": n} for r, n in rows]}


def concept_map(session: Session, *, min_shared: int = 3) -> dict:
    """Concept-to-concept edges weighted by shared ayat — the map view."""
    rows = session.execute(
        sql_text(
            """
            select c1.slug, c2.slug, count(*) as shared
            from concept_ayah a1
            join concept_ayah a2 on a1.ayah_id = a2.ayah_id and a1.concept_id < a2.concept_id
            join concept c1 on c1.id = a1.concept_id
            join concept c2 on c2.id = a2.concept_id
            group by c1.slug, c2.slug
            having count(*) >= :min_shared
            order by shared desc
            """
        ),
        {"min_shared": min_shared},
    ).all()
    nodes = defaultdict(int)
    for a, b, n in rows:
        nodes[a] += n
        nodes[b] += n
    return {
        "nodes": [{"slug": slug, "degree": degree} for slug, degree in sorted(nodes.items())],
        "edges": [{"source": a, "target": b, "shared_ayat": n} for a, b, n in rows],
    }
