"""Deterministic retrieval — pure SQL, 100% recall.

When a researcher asks for "every occurrence of root ع-ل-م", the only
acceptable answer is *every* occurrence. Nothing in this module ranks,
truncates silently or approximates: results carry the true total even when the
caller asks for a page of them, and ``exhaustive=True`` is a claim the test
suite checks against independently computed counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from qra.arabic import loose_form, normalise_root, search_form
from qra.citations import Citation, ayah_citation, morphology_citation
from qra.models import Ayah, Lemma, Root, Segment, Surah, Word
from qra.retrieval.base import CorpusFilter, Span


@dataclass
class MorphologyFilter:
    """Filters over the QAC analysis of a segment."""

    pos_class: str | None = None  # N | V | P
    tag: str | None = None  # PN, DET, COND, RSLT, ...
    aspect: str | None = None  # PERF | IMPF | IMPV
    verb_form: str | None = None  # 1..10 (QAC roman form, stored as digits)
    mood: str | None = None  # IND | SUBJ | JUS
    voice: str | None = None  # ACT | PASS
    case: str | None = None  # NOM | ACC | GEN
    state: str | None = None  # DEF | INDEF
    person: str | None = None
    gender: str | None = None
    number: str | None = None
    derivation: str | None = None  # ACT_PCPL | PASS_PCPL | VN | ADJ
    include_affixes: bool = False

    def apply(self, stmt: Select) -> Select:
        if self.pos_class:
            stmt = stmt.where(Segment.pos_class == self.pos_class)
        if self.tag:
            stmt = stmt.where(Segment.tag == self.tag)
        if self.aspect:
            stmt = stmt.where(Segment.aspect == self.aspect)
        if self.verb_form:
            stmt = stmt.where(Segment.verb_form == str(self.verb_form))
        if self.mood:
            stmt = stmt.where(Segment.mood == self.mood)
        if self.voice:
            stmt = stmt.where(Segment.voice == self.voice)
        if self.case:
            stmt = stmt.where(Segment.case_ == self.case)
        if self.state:
            stmt = stmt.where(Segment.state == self.state)
        if self.person:
            stmt = stmt.where(Segment.person == str(self.person))
        if self.gender:
            stmt = stmt.where(Segment.gender == self.gender)
        if self.number:
            stmt = stmt.where(Segment.number == self.number)
        if self.derivation:
            stmt = stmt.where(Segment.derivation == self.derivation)
        if not self.include_affixes:
            stmt = stmt.where(Segment.is_prefix.is_(False), Segment.is_suffix.is_(False))
        return stmt

    def describe(self) -> str:
        parts = [
            f"{name}={value}"
            for name, value in self.__dict__.items()
            if value and name != "include_affixes"
        ]
        return ", ".join(parts) or "any form"


@dataclass
class RootQuery:
    root: str
    filters: CorpusFilter = field(default_factory=CorpusFilter)
    morphology: MorphologyFilter = field(default_factory=MorphologyFilter)
    limit: int | None = None
    offset: int = 0


@dataclass
class OccurrenceResult:
    """An exhaustive answer plus the page of spans the caller asked for."""

    query: str
    root: str | None = None
    root_display: str | None = None
    lemma: str | None = None
    total_occurrences: int = 0
    total_ayat: int = 0
    hits: list[Span] = field(default_factory=list)
    by_surah: dict[int, int] = field(default_factory=dict)
    by_revelation_place: dict[str, int] = field(default_factory=dict)
    exhaustive: bool = True
    truncated: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "root": self.root,
            "root_display": self.root_display,
            "lemma": self.lemma,
            "total_occurrences": self.total_occurrences,
            "total_ayat": self.total_ayat,
            "by_surah": self.by_surah,
            "by_revelation_place": self.by_revelation_place,
            "exhaustive": self.exhaustive,
            "truncated": self.truncated,
            "description": self.description,
            "hits": [h.to_dict() for h in self.hits],
        }


def _segment_stmt(filters: CorpusFilter, morphology: MorphologyFilter) -> Select:
    stmt = select(Segment.id).join(Ayah, Segment.ayah_id == Ayah.id)
    stmt = filters.apply(stmt)
    return morphology.apply(stmt)


def _spans_from_segments(session: Session, segment_ids: list[int]) -> list[Span]:
    if not segment_ids:
        return []
    rows = session.execute(
        select(Segment, Word, Ayah)
        .join(Word, Segment.word_id == Word.id)
        .join(Ayah, Segment.ayah_id == Ayah.id)
        .where(Segment.id.in_(segment_ids))
        .order_by(Ayah.id, Word.position, Segment.position)
    ).all()
    spans: list[Span] = []
    for segment, word, ayah in rows:
        citation: Citation = ayah_citation(ayah)
        spans.append(
            Span(
                kind="ayah",
                text=ayah.text_uthmani,
                citation=citation,
                ayah_id=ayah.id,
                ref=f"{ayah.surah_id}:{ayah.ayah_num}",
                retrieval_mode="deterministic",
                highlights=[word.position],
                extra={
                    "word": word.text,
                    "word_position": word.position,
                    "segment_form": segment.form,
                    "pos_class": segment.pos_class,
                    "tag": segment.tag,
                    "aspect": segment.aspect,
                    "verb_form": segment.verb_form,
                    "mood": segment.mood,
                    "voice": segment.voice,
                    "case": segment.case_,
                    "derivation": segment.derivation,
                    "revelation_place": ayah.revelation_place,
                    "revelation_order": ayah.revelation_order,
                    "morphology_citation": morphology_citation(segment, ayah).to_dict(),
                },
            )
        )
    return spans


def _merge_by_ayah(spans: list[Span]) -> list[Span]:
    """Collapse several hits inside one ayah into a single span with N highlights."""
    merged: dict[int, Span] = {}
    for span in spans:
        existing = merged.get(span.ayah_id)
        if existing is None:
            merged[span.ayah_id] = span
            span.extra = dict(span.extra)
            span.extra["matches"] = [
                {
                    "word": span.extra.get("word"),
                    "position": span.extra.get("word_position"),
                    "segment_form": span.extra.get("segment_form"),
                }
            ]
        else:
            existing.highlights = sorted(set(existing.highlights + span.highlights))
            existing.extra["matches"].append(
                {
                    "word": span.extra.get("word"),
                    "position": span.extra.get("word_position"),
                    "segment_form": span.extra.get("segment_form"),
                }
            )
    return list(merged.values())


def search_root(
    session: Session, query: RootQuery, *, group_by_ayah: bool = True
) -> OccurrenceResult:
    """Every occurrence of a root, optionally narrowed by structure/morphology."""
    key = normalise_root(query.root)
    root = session.scalar(select(Root).where(Root.root == key))
    result = OccurrenceResult(
        query=query.root,
        root=key,
        root_display=root.root_display if root else None,
        description=(
            f"root {key or query.root} in {query.filters.describe()}; "
            f"morphology: {query.morphology.describe()}"
        ),
    )
    if root is None:
        return result

    base = _segment_stmt(query.filters, query.morphology).where(Segment.root_id == root.id)

    counts = session.execute(
        select(func.count(Segment.id), func.count(func.distinct(Segment.ayah_id)))
        .select_from(Segment)
        .join(Ayah, Segment.ayah_id == Ayah.id)
        .where(Segment.id.in_(base))
    ).one()
    result.total_occurrences, result.total_ayat = counts

    result.by_surah = {
        surah: n
        for surah, n in session.execute(
            select(Segment.surah_id, func.count(Segment.id))
            .where(Segment.id.in_(base))
            .group_by(Segment.surah_id)
            .order_by(Segment.surah_id)
        ).all()
    }
    result.by_revelation_place = {
        place: n
        for place, n in session.execute(
            select(Ayah.revelation_place, func.count(Segment.id))
            .join(Segment, Segment.ayah_id == Ayah.id)
            .where(Segment.id.in_(base))
            .group_by(Ayah.revelation_place)
        ).all()
    }

    ordered = (
        select(Segment.id)
        .join(Ayah, Segment.ayah_id == Ayah.id)
        .where(Segment.id.in_(base))
        .order_by(Ayah.id, Segment.word_id, Segment.position)
    )
    if query.limit is not None:
        ordered = ordered.limit(query.limit).offset(query.offset)
        result.truncated = query.offset + query.limit < result.total_occurrences
    segment_ids = list(session.scalars(ordered).all())
    spans = _spans_from_segments(session, segment_ids)
    result.hits = _merge_by_ayah(spans) if group_by_ayah else spans
    return result


def search_lemma(
    session: Session,
    lemma: str,
    *,
    filters: CorpusFilter | None = None,
    morphology: MorphologyFilter | None = None,
    limit: int | None = None,
) -> OccurrenceResult:
    filters = filters or CorpusFilter()
    morphology = morphology or MorphologyFilter()
    key = search_form(lemma)
    lemma_ids = list(session.scalars(select(Lemma.id).where(Lemma.lemma == key)).all())
    result = OccurrenceResult(
        query=lemma, lemma=key, description=f"lemma {key} in {filters.describe()}"
    )
    if not lemma_ids:
        return result

    base = _segment_stmt(filters, morphology).where(Segment.lemma_id.in_(lemma_ids))
    result.total_occurrences, result.total_ayat = session.execute(
        select(func.count(Segment.id), func.count(func.distinct(Segment.ayah_id))).where(
            Segment.id.in_(base)
        )
    ).one()
    ordered = select(Segment.id).where(Segment.id.in_(base)).order_by(Segment.ayah_id, Segment.id)
    if limit:
        ordered = ordered.limit(limit)
        result.truncated = limit < result.total_occurrences
    result.hits = _merge_by_ayah(_spans_from_segments(session, list(session.scalars(ordered).all())))
    return result


def search_morphology(
    session: Session,
    *,
    filters: CorpusFilter | None = None,
    morphology: MorphologyFilter | None = None,
    root: str | None = None,
    limit: int | None = 200,
) -> OccurrenceResult:
    """The general form: e.g. every imperative verb from root ق-و-ل in Makki surahs."""
    filters = filters or CorpusFilter()
    morphology = morphology or MorphologyFilter()
    if root:
        return search_root(
            session, RootQuery(root=root, filters=filters, morphology=morphology, limit=limit)
        )

    base = _segment_stmt(filters, morphology)
    result = OccurrenceResult(
        query=morphology.describe(),
        description=f"{morphology.describe()} in {filters.describe()}",
    )
    result.total_occurrences, result.total_ayat = session.execute(
        select(func.count(Segment.id), func.count(func.distinct(Segment.ayah_id))).where(
            Segment.id.in_(base)
        )
    ).one()
    ordered = select(Segment.id).where(Segment.id.in_(base)).order_by(Segment.ayah_id, Segment.id)
    if limit:
        ordered = ordered.limit(limit)
        result.truncated = limit < result.total_occurrences
    result.hits = _merge_by_ayah(_spans_from_segments(session, list(session.scalars(ordered).all())))
    return result


def search_phrase(
    session: Session,
    phrase: str,
    *,
    filters: CorpusFilter | None = None,
    limit: int | None = None,
    ignore_diacritics: bool = True,
) -> OccurrenceResult:
    """Exact Arabic phrase search, in two tiers.

    ``ignore_diacritics`` searches the folded column, so ``الرحمن`` matches
    ``ٱلرَّحۡمَٰنِ``. With it off, the raw Uthmani text is matched literally.

    The strict tier indexes the Imlaei orthography — the spelling a researcher
    types. If it finds nothing, an alef-insensitive tier runs, because the
    Uthmani script writes many long vowels as a superscript alef and no single
    fold reconciles ``الرحمن`` (no alef) with ``العالمين`` (alef). The looser
    tier over-merges, so when it is used the result says so in ``description``
    and in ``matched_tier``.
    """
    filters = filters or CorpusFilter()
    needle = search_form(phrase) if ignore_diacritics else phrase
    column = Ayah.text_search if ignore_diacritics else Ayah.text_uthmani
    tier = "exact"

    if ignore_diacritics:
        strict_hits = session.scalar(
            filters.apply(
                select(func.count()).select_from(Ayah).where(Ayah.text_search.like(f"%{needle}%"))
            )
        )
        if not strict_hits:
            loose_needle = loose_form(phrase)
            if loose_needle and session.scalar(
                filters.apply(
                    select(func.count())
                    .select_from(Ayah)
                    .where(Ayah.text_loose.like(f"%{loose_needle}%"))
                )
            ):
                needle, column, tier = loose_needle, Ayah.text_loose, "alef_insensitive"

    stmt = select(Ayah).where(column.like(f"%{needle}%"))
    stmt = filters.apply(stmt)
    total = session.scalar(
        filters.apply(select(func.count()).select_from(Ayah).where(column.like(f"%{needle}%")))
    )
    ordered = stmt.order_by(Ayah.id)
    if limit:
        ordered = ordered.limit(limit)

    result = OccurrenceResult(
        query=phrase,
        total_ayat=total or 0,
        description=f'exact phrase "{phrase}" in {filters.describe()}'
        + (" (diacritics ignored)" if ignore_diacritics else "")
        + (
            " — no exact match, so an ALEF-INSENSITIVE match was used; it can "
            "over-merge (قال/قل), so check each hit"
            if tier == "alef_insensitive"
            else ""
        ),
        truncated=bool(limit and total and limit < total),
    )
    # The occurrence total must cover every match, not just the page being
    # returned — a truncated count would quietly break the exhaustiveness claim.
    result.total_occurrences = sum(
        body.count(needle)
        for (body,) in session.execute(
            filters.apply(select(column).where(column.like(f"%{needle}%")))
        ).all()
    )

    for ayah in session.scalars(ordered).all():
        haystack = (
            ayah.text_loose
            if tier == "alef_insensitive"
            else (ayah.text_search if ignore_diacritics else ayah.text_uthmani)
        )
        count = haystack.count(needle)
        positions = _phrase_positions(haystack.split(), needle.split())
        result.hits.append(
            Span(
                kind="ayah",
                text=ayah.text_uthmani,
                citation=ayah_citation(ayah),
                ayah_id=ayah.id,
                ref=f"{ayah.surah_id}:{ayah.ayah_num}",
                retrieval_mode="deterministic",
                highlights=positions,
                extra={
                    "occurrences_in_ayah": count,
                    "revelation_place": ayah.revelation_place,
                    "matched_tier": tier,
                },
            )
        )
    return result


def _phrase_positions(haystack: list[str], needle: list[str]) -> list[int]:
    if not needle:
        return []
    out = []
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i : i + len(needle)] == needle:
            out.extend(range(i + 1, i + len(needle) + 1))
    return out


def count_occurrences(
    session: Session,
    *,
    root: str | None = None,
    lemma: str | None = None,
    phrase: str | None = None,
    filters: CorpusFilter | None = None,
    morphology: MorphologyFilter | None = None,
) -> dict:
    """Counts only — the cheap path for analytics and for agent tool calls."""
    filters = filters or CorpusFilter()
    morphology = morphology or MorphologyFilter()
    if root:
        result = search_root(session, RootQuery(root=root, filters=filters, morphology=morphology, limit=0))
    elif lemma:
        result = search_lemma(session, lemma, filters=filters, morphology=morphology, limit=0)
    elif phrase:
        result = search_phrase(session, phrase, filters=filters, limit=0)
    else:
        raise ValueError("count_occurrences needs one of root, lemma or phrase")
    return {
        "query": result.query,
        "total_occurrences": result.total_occurrences,
        "total_ayat": result.total_ayat,
        "by_surah": result.by_surah,
        "by_revelation_place": result.by_revelation_place,
        "scope": filters.describe(),
        "exhaustive": True,
    }


# ---------------------------------------------------------------------------
# Direct fetches
# ---------------------------------------------------------------------------


def get_ayah(session: Session, surah: int, ayah: int) -> Span | None:
    row = session.scalar(select(Ayah).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah))
    if row is None:
        return None
    return Span(
        kind="ayah",
        text=row.text_uthmani,
        citation=ayah_citation(row),
        ayah_id=row.id,
        ref=f"{row.surah_id}:{row.ayah_num}",
        extra={
            "text_imlaei": row.text_imlaei,
            "juz": row.juz,
            "page": row.page,
            "ruku": row.ruku,
            "sajda": row.sajda,
            "revelation_place": row.revelation_place,
            "revelation_order": row.revelation_order,
            "word_count": row.word_count,
        },
    )


def get_ayah_by_id(session: Session, ayah_id: int) -> Span | None:
    row = session.get(Ayah, ayah_id)
    if row is None:
        return None
    return get_ayah(session, row.surah_id, row.ayah_num)


def get_range(session: Session, surah: int, start: int, end: int) -> list[Span]:
    rows = session.scalars(
        select(Ayah)
        .where(Ayah.surah_id == surah, Ayah.ayah_num >= start, Ayah.ayah_num <= end)
        .order_by(Ayah.ayah_num)
    ).all()
    return [
        Span(
            kind="ayah",
            text=row.text_uthmani,
            citation=ayah_citation(row),
            ayah_id=row.id,
            ref=f"{row.surah_id}:{row.ayah_num}",
        )
        for row in rows
    ]


def get_morphology(session: Session, surah: int, ayah: int) -> dict:
    """Word-by-word analysis of one ayah, with citation."""
    row = session.scalar(select(Ayah).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah))
    if row is None:
        return {}
    words = session.scalars(
        select(Word).where(Word.ayah_id == row.id).order_by(Word.position)
    ).all()
    segments_by_word: dict[int, list[Segment]] = {}
    for segment in session.scalars(
        select(Segment).where(Segment.ayah_id == row.id).order_by(Segment.word_id, Segment.position)
    ).all():
        segments_by_word.setdefault(segment.word_id, []).append(segment)

    roots = {
        r.id: r for r in session.scalars(select(Root).where(Root.id.in_([w.root_id for w in words if w.root_id]))).all()
    }
    lemmas = {
        lem.id: lem
        for lem in session.scalars(
            select(Lemma).where(Lemma.id.in_([w.lemma_id for w in words if w.lemma_id]))
        ).all()
    }

    return {
        "ref": f"{surah}:{ayah}",
        "ayah_id": row.id,
        "text": row.text_uthmani,
        "citation": ayah_citation(row).to_dict(),
        "words": [
            {
                "position": word.position,
                "text": word.text,
                "root": roots[word.root_id].root_display if word.root_id in roots else None,
                "root_occurrences": roots[word.root_id].occurrence_count
                if word.root_id in roots
                else None,
                "lemma": lemmas[word.lemma_id].lemma_display if word.lemma_id in lemmas else None,
                "pos": word.pos,
                "segments": [
                    {
                        "position": seg.position,
                        "form": seg.form,
                        "pos_class": seg.pos_class,
                        "tag": seg.tag,
                        "aspect": seg.aspect,
                        "verb_form": seg.verb_form,
                        "mood": seg.mood,
                        "voice": seg.voice,
                        "case": seg.case_,
                        "state": seg.state,
                        "person": seg.person,
                        "gender": seg.gender,
                        "number": seg.number,
                        "derivation": seg.derivation,
                        "is_prefix": seg.is_prefix,
                        "is_suffix": seg.is_suffix,
                        "features": seg.features,
                    }
                    for seg in segments_by_word.get(word.id, [])
                ],
            }
            for word in words
        ],
    }


def root_profile(session: Session, root: str) -> dict:
    """Derivation family and distribution of a root — the Lisan agent's raw material."""
    key = normalise_root(root)
    row = session.scalar(select(Root).where(Root.root == key))
    if row is None:
        return {"root": key, "found": False}

    forms = session.execute(
        select(
            Segment.form,
            Segment.pos_class,
            Segment.derivation,
            Segment.aspect,
            Segment.verb_form,
            func.count(Segment.id),
        )
        .where(Segment.root_id == row.id)
        .group_by(Segment.form, Segment.pos_class, Segment.derivation, Segment.aspect, Segment.verb_form)
        .order_by(func.count(Segment.id).desc())
    ).all()

    lemmas = session.execute(
        select(Lemma.lemma_display, Lemma.occurrence_count)
        .where(Lemma.root_id == row.id)
        .order_by(Lemma.occurrence_count.desc())
    ).all()

    by_place = dict(
        session.execute(
            select(Ayah.revelation_place, func.count(Segment.id))
            .join(Segment, Segment.ayah_id == Ayah.id)
            .where(Segment.root_id == row.id)
            .group_by(Ayah.revelation_place)
        ).all()
    )
    by_surah = dict(
        session.execute(
            select(Segment.surah_id, func.count(Segment.id))
            .where(Segment.root_id == row.id)
            .group_by(Segment.surah_id)
            .order_by(Segment.surah_id)
        ).all()
    )
    verb_forms = dict(
        session.execute(
            select(Segment.verb_form, func.count(Segment.id))
            .where(Segment.root_id == row.id, Segment.verb_form.isnot(None))
            .group_by(Segment.verb_form)
            .order_by(Segment.verb_form)
        ).all()
    )

    return {
        "root": row.root,
        "root_display": row.root_display,
        "found": True,
        "occurrence_count": row.occurrence_count,
        "ayah_count": row.ayah_count,
        "by_revelation_place": by_place,
        "by_surah": by_surah,
        "verb_forms": verb_forms,
        "lemmas": [{"lemma": lemma, "count": n} for lemma, n in lemmas],
        "surface_forms": [
            {
                "form": form,
                "pos_class": pos_class,
                "derivation": derivation,
                "aspect": aspect,
                "verb_form": verb_form,
                "count": n,
            }
            for form, pos_class, derivation, aspect, verb_form, n in forms
        ],
        "citation": {
            "kind": "morphology",
            "edition_name": "Quranic Arabic Corpus (morphology)",
            "ref": f"root {row.root_display}",
        },
    }


def list_surahs(session: Session) -> list[dict]:
    return [
        {
            "id": s.id,
            "name_ar": s.name_ar,
            "name_en": s.name_en,
            "name_translit": s.name_translit,
            "ayah_count": s.ayah_count,
            "revelation_place": s.revelation_place,
            "revelation_order": s.revelation_order,
            "revelation_order_scheme": s.revelation_order_scheme,
        }
        for s in session.scalars(select(Surah).order_by(Surah.id)).all()
    ]
