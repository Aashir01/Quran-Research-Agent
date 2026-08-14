"""BM25 over translations, tafsir, hadith and the Arabic text.

Scored in SQL against the inverted index built at ingest. Okapi BM25 with the
standard k1=1.2, b=0.75; document length and average length come from
``search_doc`` so scores are stable across runs.

Postgres full-text search is deliberately not used: it ships no Arabic or Urdu
dictionary, so ``to_tsvector('simple', …)`` would give us a worse version of
this with none of the transparency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from qra.arabic import tokenise_multilingual
from qra.citations import (
    ayah_citation,
    hadith_citation,
    tafsir_citation,
    translation_citation,
)
from qra.models import Ayah, Edition, Hadith, SearchDoc, TafsirEntry, Translation
from qra.retrieval.base import CorpusFilter, Span

K1 = 1.2
B = 0.75


@dataclass
class LexicalHit:
    doc_id: int
    kind: str
    ref_id: int
    ayah_id: int | None
    edition_id: int | None
    score: float
    matched_terms: list[str]


def _corpus_stats(session: Session, kinds: tuple[str, ...], languages: tuple[str, ...] | None):
    stmt = select(func.count(SearchDoc.id), func.avg(SearchDoc.length)).where(
        SearchDoc.kind.in_(kinds)
    )
    if languages:
        stmt = stmt.where(SearchDoc.language.in_(languages))
    total, avg = session.execute(stmt).one()
    return int(total or 0), float(avg or 1.0)


def search_lexical(
    session: Session,
    query: str,
    *,
    kinds: tuple[str, ...] = ("translation", "ayah"),
    languages: tuple[str, ...] | None = None,
    editions: tuple[str, ...] | None = None,
    filters: CorpusFilter | None = None,
    limit: int = 20,
) -> list[Span]:
    terms = tokenise_multilingual(query)
    if not terms:
        return []
    total_docs, avg_len = _corpus_stats(session, kinds, languages)
    if total_docs == 0:
        return []

    params = {
        "terms": terms,
        "kinds": list(kinds),
        "k1": K1,
        "b": B,
        "avg_len": avg_len,
        "n_docs": total_docs,
        "limit": limit,
    }
    lang_clause = ""
    if languages:
        lang_clause = " and d.language = any(:languages)"
        params["languages"] = list(languages)
    edition_clause = ""
    if editions:
        edition_clause = " and e.slug = any(:editions)"
        params["editions"] = list(editions)

    # IDF uses the standard BM25+ form with the 0.5 smoothing; the max() guard
    # keeps a term appearing in more than half the corpus from scoring negative.
    sql = f"""
        select d.id, d.kind, d.ref_id, d.ayah_id, d.edition_id,
               sum(
                   greatest(ln((:n_docs - t.df + 0.5) / (t.df + 0.5) + 1.0), 0.0)
                   * ((p.tf * (:k1 + 1)) /
                      (p.tf + :k1 * (1 - :b + :b * (d.length::float / :avg_len))))
               ) as score,
               array_agg(distinct p.term) as matched
        from search_posting p
        join search_term t on t.term = p.term
        join search_doc d on d.id = p.doc_id
        left join edition e on e.id = d.edition_id
        where p.term = any(:terms)
          and d.kind = any(:kinds)
          {lang_clause}
          {edition_clause}
        group by d.id, d.kind, d.ref_id, d.ayah_id, d.edition_id
        order by score desc
        limit :limit
    """
    rows = session.execute(sql_text(sql), params).all()
    hits = [
        LexicalHit(doc_id=r[0], kind=r[1], ref_id=r[2], ayah_id=r[3], edition_id=r[4], score=float(r[5]), matched_terms=list(r[6]))
        for r in rows
    ]
    spans = _hydrate(session, hits)
    if filters and not filters.is_empty:
        allowed = {
            aid
            for (aid,) in session.execute(filters.apply(select(Ayah.id))).all()
        }
        spans = [s for s in spans if s.ayah_id is None or s.ayah_id in allowed]
    return spans


def _hydrate(session: Session, hits: list[LexicalHit]) -> list[Span]:
    """Turn scored doc ids back into cited spans, in one round trip per kind."""
    editions = {e.id: e for e in session.scalars(select(Edition)).all()}
    by_kind: dict[str, list[LexicalHit]] = {}
    for hit in hits:
        by_kind.setdefault(hit.kind, []).append(hit)

    spans: dict[int, Span] = {}

    if "ayah" in by_kind:
        ids = [h.ref_id for h in by_kind["ayah"]]
        rows = {a.id: a for a in session.scalars(select(Ayah).where(Ayah.id.in_(ids))).all()}
        for hit in by_kind["ayah"]:
            ayah = rows.get(hit.ref_id)
            if ayah:
                spans[hit.doc_id] = Span(
                    kind="ayah",
                    text=ayah.text_uthmani,
                    citation=ayah_citation(ayah),
                    ayah_id=ayah.id,
                    ref=f"{ayah.surah_id}:{ayah.ayah_num}",
                    score=hit.score,
                    retrieval_mode="lexical",
                    extra={"matched_terms": hit.matched_terms},
                )

    if "translation" in by_kind:
        ids = [h.ref_id for h in by_kind["translation"]]
        rows = {t.id: t for t in session.scalars(select(Translation).where(Translation.id.in_(ids))).all()}
        for hit in by_kind["translation"]:
            row = rows.get(hit.ref_id)
            if row:
                edition = editions[row.edition_id]
                spans[hit.doc_id] = Span(
                    kind="translation",
                    text=row.text,
                    citation=translation_citation(row, edition),
                    ayah_id=row.ayah_id,
                    ref=f"{row.surah_id}:{row.ayah_num}",
                    score=hit.score,
                    retrieval_mode="lexical",
                    extra={"matched_terms": hit.matched_terms, "edition": edition.slug},
                )

    if "tafsir" in by_kind:
        ids = [h.ref_id for h in by_kind["tafsir"]]
        rows = {t.id: t for t in session.scalars(select(TafsirEntry).where(TafsirEntry.id.in_(ids))).all()}
        for hit in by_kind["tafsir"]:
            row = rows.get(hit.ref_id)
            if row:
                edition = editions[row.edition_id]
                spans[hit.doc_id] = Span(
                    kind="tafsir",
                    text=row.text,
                    citation=tafsir_citation(row, edition),
                    ayah_id=row.ayah_id_start,
                    ref=f"{row.surah_id}:{row.ayah_start}-{row.ayah_end}",
                    score=hit.score,
                    retrieval_mode="lexical",
                    extra={"matched_terms": hit.matched_terms, "edition": edition.slug},
                )

    if "hadith" in by_kind:
        ids = [h.ref_id for h in by_kind["hadith"]]
        rows = {h.id: h for h in session.scalars(select(Hadith).where(Hadith.id.in_(ids))).all()}
        for hit in by_kind["hadith"]:
            row = rows.get(hit.ref_id)
            if row:
                edition = editions[row.edition_id]
                spans[hit.doc_id] = Span(
                    kind="hadith",
                    text=row.text_ar or row.text_translation or "",
                    citation=hadith_citation(row, edition),
                    score=hit.score,
                    retrieval_mode="lexical",
                    extra={
                        "matched_terms": hit.matched_terms,
                        "grading": row.grading,
                        "translation": row.text_translation,
                    },
                )

    return [spans[h.doc_id] for h in hits if h.doc_id in spans]


def explain_score(session: Session, query: str, doc_id: int) -> dict:
    """Per-term BM25 breakdown. Researchers get to see why a hit ranked."""
    terms = tokenise_multilingual(query)
    doc = session.get(SearchDoc, doc_id)
    if doc is None or not terms:
        return {}
    total_docs, avg_len = _corpus_stats(session, (doc.kind,), (doc.language,))
    rows = session.execute(
        sql_text(
            """
            select p.term, p.tf, t.df from search_posting p
            join search_term t on t.term = p.term
            where p.doc_id = :doc and p.term = any(:terms)
            """
        ),
        {"doc": doc_id, "terms": terms},
    ).all()
    breakdown = []
    for term, tf, df in rows:
        idf = max(math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0), 0.0)
        tf_component = (tf * (K1 + 1)) / (tf + K1 * (1 - B + B * (doc.length / avg_len)))
        breakdown.append(
            {"term": term, "tf": tf, "df": df, "idf": round(idf, 4), "score": round(idf * tf_component, 4)}
        )
    return {
        "doc_id": doc_id,
        "kind": doc.kind,
        "length": doc.length,
        "avg_length": round(avg_len, 2),
        "corpus_size": total_docs,
        "terms": breakdown,
        "total": round(sum(b["score"] for b in breakdown), 4),
    }
