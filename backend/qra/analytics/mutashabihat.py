"""Mutashabihat — near-identical verses, with the deltas highlighted.

Pairs are detected at ingest by word-shingle similarity over the folded text;
this module queries them and computes the word-level diff that makes the pair
useful: what changed between 2:58 and 7:161 is the entire point of comparing
them.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.citations import ayah_citation
from qra.models import Ayah, AyahLink


def _diff_words(a: str, b: str) -> list[dict]:
    """Word-level diff of two ayat, in reading order."""
    left, right = a.split(), b.split()
    ops = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=left, b=right).get_opcodes():
        ops.append(
            {
                "op": tag,
                "a": left[i1:i2],
                "b": right[j1:j2],
                "a_position": i1 + 1,
                "b_position": j1 + 1,
            }
        )
    return ops


def similar_to(
    session: Session,
    ayah_id: int,
    *,
    min_score: float = 0.6,
    limit: int = 20,
    kinds: tuple[str, ...] = ("mutashabih", "parallel"),
) -> dict:
    ayah = session.get(Ayah, ayah_id)
    if ayah is None:
        return {}
    rows = session.execute(
        select(AyahLink, Ayah)
        .join(Ayah, Ayah.id == AyahLink.dst_ayah_id)
        .where(
            AyahLink.src_ayah_id == ayah_id,
            AyahLink.kind.in_(kinds),
            AyahLink.score >= min_score,
        )
        .order_by(AyahLink.score.desc())
        .limit(limit)
    ).all()

    return {
        "ayah": {
            "id": ayah.id,
            "ref": f"{ayah.surah_id}:{ayah.ayah_num}",
            "text": ayah.text_uthmani,
            "citation": ayah_citation(ayah).to_dict(),
        },
        "matches": [
            {
                "ayah_id": other.id,
                "ref": f"{other.surah_id}:{other.ayah_num}",
                "text": other.text_uthmani,
                "kind": link.kind,
                "score": round(link.score, 3),
                "identical": bool(link.detail.get("identical")),
                "shared_roots": link.detail.get("shared_roots"),
                "revelation_place": other.revelation_place,
                "diff": _diff_words(ayah.text_uthmani, other.text_uthmani),
                "citation": ayah_citation(other).to_dict(),
            }
            for link, other in rows
        ],
        "method": (
            "Two tiers. 'mutashabih' = word-shingle Jaccard over diacritic-folded text (n=3): "
            "near-identical wording. 'parallel' = content-root Jaccard: the same episode told "
            "in different words, which the string tier cannot see (2:58 vs 7:161 scores 0.08 "
            "on shingles and matches on roots)."
        ),
    }


def clusters(session: Session, *, min_score: float = 0.75, min_size: int = 3, limit: int = 50) -> dict:
    """Groups of three or more mutually similar ayat — repeated refrains.

    Connected components over the similarity graph. Surah ar-Rahman's refrain
    and the repeated formulae in ash-Shu'ara' are what this surfaces.
    """
    rows = session.execute(
        select(AyahLink.src_ayah_id, AyahLink.dst_ayah_id, AyahLink.score).where(
            AyahLink.kind == "mutashabih", AyahLink.score >= min_score
        )
    ).all()

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for src, dst, _score in rows:
        union(src, dst)

    groups: dict[int, set[int]] = {}
    for node in list(parent):
        groups.setdefault(find(node), set()).add(node)

    sizable = [g for g in groups.values() if len(g) >= min_size]
    sizable.sort(key=len, reverse=True)

    out = []
    for group in sizable[:limit]:
        ayat = session.scalars(
            select(Ayah).where(Ayah.id.in_(sorted(group))).order_by(Ayah.id)
        ).all()
        out.append(
            {
                "size": len(group),
                "surahs": sorted({a.surah_id for a in ayat}),
                "ayat": [
                    {"ayah_id": a.id, "ref": f"{a.surah_id}:{a.ayah_num}", "text": a.text_uthmani}
                    for a in ayat
                ],
            }
        )
    return {"clusters": out, "cluster_count": len(sizable), "min_score": min_score}


def summary(session: Session) -> dict:
    total = session.scalar(
        select(func.count()).select_from(AyahLink).where(AyahLink.kind == "mutashabih")
    )
    cross_surah = session.scalar(
        select(func.count())
        .select_from(AyahLink)
        .join(Ayah, Ayah.id == AyahLink.dst_ayah_id)
        .where(AyahLink.kind == "mutashabih")
    )
    return {"directed_links": total, "pairs": (total or 0) // 2, "scanned": cross_surah}
