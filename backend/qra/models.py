"""Database schema — the single source of truth.

Design rules that the rest of the system depends on:

1. Every text-bearing row carries an immutable citation payload (surah:ayah,
   edition, author, source URL, page/reference where one exists). Nothing is
   ingested without it — :func:`qra.citations.citation_for` will raise if a row
   cannot produce one.
2. Every Arabic column that is searched has a normalised twin (``*_search``)
   produced by :func:`qra.arabic.search_form`, so exact matching is exhaustive
   regardless of diacritics.
3. Surrogate keys are stable and meaningful where possible: ``ayah.id`` is the
   canonical 1..6236 mushaf index, so it can be used as a citation anchor
   directly in notes, hypotheses and agent output.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")
FloatArray = JSON().with_variant(ARRAY(Float), "postgresql")


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Layer 1: corpus
# ---------------------------------------------------------------------------


class Surah(Base):
    __tablename__ = "surah"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name_ar: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str] = mapped_column(String(128))
    name_translit: Mapped[str] = mapped_column(String(128))
    ayah_count: Mapped[int] = mapped_column(Integer)
    revelation_place: Mapped[str] = mapped_column(String(8))  # makki | madani
    # Egyptian standard chronological order. Contested — see
    # data/metadata/revelation_order.json for the caveat carried into the UI.
    revelation_order: Mapped[int] = mapped_column(Integer, index=True)
    revelation_order_scheme: Mapped[str] = mapped_column(String(32), default="egyptian_standard")
    has_bismillah: Mapped[bool] = mapped_column(Boolean, default=True)

    ayat: Mapped[list[Ayah]] = relationship(back_populates="surah")

    __table_args__ = (
        CheckConstraint("revelation_place in ('makki','madani')", name="ck_surah_place"),
    )


class Ayah(Base):
    """One verse. ``id`` is the canonical 1..6236 index across the whole mushaf."""

    __tablename__ = "ayah"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    surah_id: Mapped[int] = mapped_column(ForeignKey("surah.id"), index=True)
    ayah_num: Mapped[int] = mapped_column(Integer)

    text_uthmani: Mapped[str] = mapped_column(Text)
    text_imlaei: Mapped[str] = mapped_column(Text)
    # Primary phrase key, built from the IMLAEI text: it uses the standard
    # orthography a researcher actually types. Folding the Uthmani text instead
    # loses the superscript alef, so العالمين would never match ٱلۡعَٰلَمِينَ.
    text_search: Mapped[str] = mapped_column(Text)
    # Alef-insensitive fallback key — reconciles the two orthographies where no
    # single fold can. Only ever used as a labelled second tier.
    text_loose: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer)
    letter_count: Mapped[int] = mapped_column(Integer)

    # Denormalised for filter speed — the corpus is immutable, so the usual
    # objection to denormalisation (drift) does not apply.
    revelation_place: Mapped[str] = mapped_column(String(8), index=True)
    revelation_order: Mapped[int] = mapped_column(Integer, index=True)

    juz: Mapped[int] = mapped_column(Integer, index=True)
    hizb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manzil: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ruku: Mapped[int] = mapped_column(Integer, index=True)
    page: Mapped[int] = mapped_column(Integer, index=True)
    sajda: Mapped[bool] = mapped_column(Boolean, default=False)

    surah: Mapped[Surah] = relationship(back_populates="ayat")
    words: Mapped[list[Word]] = relationship(back_populates="ayah")

    __table_args__ = (
        UniqueConstraint("surah_id", "ayah_num", name="uq_ayah_ref"),
        Index("ix_ayah_search", "text_search"),
        Index("ix_ayah_loose", "text_loose"),
    )

    @property
    def ref(self) -> str:
        return f"{self.surah_id}:{self.ayah_num}"


class Root(Base):
    __tablename__ = "root"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # normalised
    root_display: Mapped[str] = mapped_column(String(32))
    letters: Mapped[int] = mapped_column(Integer)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    ayah_count: Mapped[int] = mapped_column(Integer, default=0)


class Lemma(Base):
    __tablename__ = "lemma"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lemma: Mapped[str] = mapped_column(String(64), index=True)  # normalised
    lemma_display: Mapped[str] = mapped_column(String(64))
    root_id: Mapped[int | None] = mapped_column(ForeignKey("root.id"), nullable=True, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("lemma", "root_id", name="uq_lemma"),)


class Word(Base):
    """A whitespace-delimited word of the Uthmani text (~77k rows)."""

    __tablename__ = "word"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    surah_id: Mapped[int] = mapped_column(Integer, index=True)
    ayah_num: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)  # 1-based within the ayah

    text: Mapped[str] = mapped_column(String(128))
    text_search: Mapped[str] = mapped_column(String(128), index=True)
    # The dominant (stem) segment's analysis, lifted for cheap filtering.
    root_id: Mapped[int | None] = mapped_column(ForeignKey("root.id"), nullable=True, index=True)
    lemma_id: Mapped[int | None] = mapped_column(ForeignKey("lemma.id"), nullable=True, index=True)
    pos: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    ayah: Mapped[Ayah] = relationship(back_populates="words")
    segments: Mapped[list[Segment]] = relationship(back_populates="word")

    __table_args__ = (UniqueConstraint("ayah_id", "position", name="uq_word_pos"),)


class Segment(Base):
    """Morphological segment from the Quranic Arabic Corpus (~128k rows).

    ``features`` keeps the full feature bundle verbatim so no analysis is lost;
    the promoted columns exist because they are what researchers filter on.
    """

    __tablename__ = "segment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("word.id"), index=True)
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    surah_id: Mapped[int] = mapped_column(Integer, index=True)
    position: Mapped[int] = mapped_column(Integer)  # 1-based within the word

    form: Mapped[str] = mapped_column(String(64))
    form_search: Mapped[str] = mapped_column(String(64), index=True)
    pos_class: Mapped[str] = mapped_column(String(8))  # N | V | P (QAC coarse class)
    tag: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    root_id: Mapped[int | None] = mapped_column(ForeignKey("root.id"), nullable=True, index=True)
    lemma_id: Mapped[int | None] = mapped_column(ForeignKey("lemma.id"), nullable=True, index=True)

    # Promoted morphology — the vocabulary a query like "every imperative verb
    # from root ق-و-ل in Makki surahs" needs.
    aspect: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)  # PERF/IMPF/IMPV
    verb_form: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)  # I..X
    mood: Mapped[str | None] = mapped_column(String(8), nullable=True)
    voice: Mapped[str | None] = mapped_column(String(8), nullable=True)
    case_: Mapped[str | None] = mapped_column("case", String(8), nullable=True)
    state: Mapped[str | None] = mapped_column(String(8), nullable=True)
    person: Mapped[str | None] = mapped_column(String(4), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(4), nullable=True)
    number: Mapped[str | None] = mapped_column(String(4), nullable=True)
    derivation: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    is_prefix: Mapped[bool] = mapped_column(Boolean, default=False)
    is_suffix: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ordinal of this segment within its ayah, across word boundaries.
    # `position` counts within the *word*, so the last segment of one word and
    # the first of the next both read as 1 — adjacency is unexpressible without
    # this. Computed once at ingest: deriving it per query with a window
    # function turned a two-segment sequence search into 92 seconds.
    ayah_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    features: Mapped[dict] = mapped_column(JSONType, default=dict)

    word: Mapped[Word] = relationship(back_populates="segments")

    __table_args__ = (UniqueConstraint("word_id", "position", name="uq_segment_pos"),)


# ---------------------------------------------------------------------------
# Editions: translations, tafsir, hadith, lexicons — all licence-gated
# ---------------------------------------------------------------------------


class Edition(Base):
    """A citable publication. No text row may exist without one."""

    __tablename__ = "edition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # quran|translation|tafsir|hadith|lexicon
    language: Mapped[str] = mapped_column(String(8), index=True)  # ar|en|ur
    name: Mapped[str] = mapped_column(String(256))
    author: Mapped[str] = mapped_column(String(256))
    direction: Mapped[str] = mapped_column(String(3), default="rtl")

    source_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(String(128))
    # public_domain | permissive | restricted | unknown
    license_status: Mapped[str] = mapped_column(String(16), index=True)
    license_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    death_year_hijri: Mapped[int | None] = mapped_column(Integer, nullable=True)
    era: Mapped[str | None] = mapped_column(String(16), nullable=True)  # classical|modern
    ingested_at: Mapped[datetime] = _now()


class Translation(Base):
    __tablename__ = "translation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id"), index=True)
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    surah_id: Mapped[int] = mapped_column(Integer, index=True)
    ayah_num: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("edition_id", "ayah_id", name="uq_translation"),)


class TafsirEntry(Base):
    """Commentary chunked by ayah range — a tafsir routinely covers 1..n ayat."""

    __tablename__ = "tafsir_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id"), index=True)
    surah_id: Mapped[int] = mapped_column(Integer, index=True)
    ayah_start: Mapped[int] = mapped_column(Integer, index=True)
    ayah_end: Mapped[int] = mapped_column(Integer, index=True)
    ayah_id_start: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    ayah_id_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)  # volume/page

    __table_args__ = (
        Index("ix_tafsir_range", "edition_id", "surah_id", "ayah_start", "ayah_end"),
    )


class Hadith(Base):
    __tablename__ = "hadith"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id"), index=True)
    collection: Mapped[str] = mapped_column(String(32), index=True)
    number: Mapped[str] = mapped_column(String(32), index=True)
    book: Mapped[str | None] = mapped_column(String(256), nullable=True)
    chapter: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_search: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Grading is surfaced loudly by the Hadith agent; unknown is never silently
    # upgraded to sahih.
    grading: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    graded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (UniqueConstraint("edition_id", "number", name="uq_hadith_ref"),)


class HadithAyahLink(Base):
    __tablename__ = "hadith_ayah_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hadith_id: Mapped[int] = mapped_column(ForeignKey("hadith.id"), index=True)
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    relation: Mapped[str] = mapped_column(String(32), default="quotes")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("hadith_id", "ayah_id", name="uq_hadith_ayah"),)


class LexiconEntry(Base):
    """Lane, Mufradat al-Raghib, Lisan al-Arab — keyed by root."""

    __tablename__ = "lexicon_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id"), index=True)
    root_id: Mapped[int | None] = mapped_column(ForeignKey("root.id"), nullable=True, index=True)
    headword: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)


# ---------------------------------------------------------------------------
# Graph layer: ayah <-> root <-> concept <-> tafsir <-> hadith
# ---------------------------------------------------------------------------


class Concept(Base):
    __tablename__ = "concept"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label_en: Mapped[str] = mapped_column(String(128))
    label_ar: Mapped[str | None] = mapped_column(String(128), nullable=True)
    label_ur: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("concept.id"), nullable=True)


class ConceptRoot(Base):
    __tablename__ = "concept_root"

    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"), primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("root.id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class ConceptAyah(Base):
    __tablename__ = "concept_ayah"

    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"), primary_key=True)
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    # derived = computed from roots; curated = a human asserted it.
    provenance: Mapped[str] = mapped_column(String(16), default="derived")


class AyahLink(Base):
    """Typed edges between ayat: mutashabihat pairs, narrative parallels, etc."""

    __tablename__ = "ayah_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    src_ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    dst_ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)

    __table_args__ = (
        UniqueConstraint("src_ayah_id", "dst_ayah_id", "kind", name="uq_ayah_link"),
    )


class Passage(Base):
    """Surah-internal structural unit produced by the Nazm agent."""

    __tablename__ = "passage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    surah_id: Mapped[int] = mapped_column(Integer, index=True)
    ayah_start: Mapped[int] = mapped_column(Integer)
    ayah_end: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    theme: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(String(24), default="system_suggested")
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)


class ConditionalStructure(Base):
    """``إِنْ / إِذَا … فَ…`` mined as condition -> consequence.

    The feature that turns "the Quran states laws governing human behaviour"
    into something a researcher can actually query and test.
    """

    __tablename__ = "conditional_structure"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ayah_id: Mapped[int] = mapped_column(ForeignKey("ayah.id"), index=True)
    surah_id: Mapped[int] = mapped_column(Integer, index=True)
    particle: Mapped[str] = mapped_column(String(16), index=True)  # in | idha | law | man | ...
    particle_form: Mapped[str] = mapped_column(String(32))
    condition_text: Mapped[str] = mapped_column(Text)
    consequence_text: Mapped[str] = mapped_column(Text)
    apodosis_marker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    condition_roots: Mapped[list] = mapped_column(JSONType, default=list)
    consequence_roots: Mapped[list] = mapped_column(JSONType, default=list)
    word_start: Mapped[int] = mapped_column(Integer)
    word_end: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)


# ---------------------------------------------------------------------------
# Search indexes (lexical + semantic)
# ---------------------------------------------------------------------------


class SearchDoc(Base):
    """A retrievable unit of text for BM25/semantic search.

    Kept separate from the source tables so one index spans ayah text,
    translations, tafsir chunks and hadith without polluting their schemas.
    """

    __tablename__ = "search_doc"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # ayah|translation|tafsir|hadith
    ref_id: Mapped[int] = mapped_column(Integer, index=True)  # PK in the source table
    edition_id: Mapped[int | None] = mapped_column(ForeignKey("edition.id"), nullable=True, index=True)
    ayah_id: Mapped[int | None] = mapped_column(ForeignKey("ayah.id"), nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(8), index=True)
    text: Mapped[str] = mapped_column(Text)
    length: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("kind", "ref_id", name="uq_search_doc"),)


class SearchPosting(Base):
    """Inverted index. BM25 is computed in SQL over these rows.

    Rolling our own rather than using ``tsvector`` because Postgres ships no
    Arabic or Urdu dictionary, and a stemmer-free index keeps scores identical
    across environments.
    """

    __tablename__ = "search_posting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(64), index=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("search_doc.id"), index=True)
    tf: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("ix_posting_term_doc", "term", "doc_id"),)


class SearchTerm(Base):
    __tablename__ = "search_term"

    term: Mapped[str] = mapped_column(String(64), primary_key=True)
    df: Mapped[int] = mapped_column(Integer)


class Embedding(Base):
    """Vector store. Uses pgvector when the extension is present; otherwise a
    float array plus brute-force cosine — over 6,236 ayat that is milliseconds.
    """

    __tablename__ = "embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("search_doc.id"), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list] = mapped_column(FloatArray)

    __table_args__ = (UniqueConstraint("doc_id", "model", name="uq_embedding"),)


# ---------------------------------------------------------------------------
# Layer 5: researcher workspace
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    # reader < researcher < reviewer < admin. Enforced as a constraint so an
    # invented role cannot be written by any code path (WP-01).
    role: Mapped[str] = mapped_column(String(16), default="researcher")
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    # Only set for local password auth; OIDC users have none.
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    monthly_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(
            "role in ('reader','researcher','reviewer','admin')", name="ck_user_role"
        ),
    )


class Note(Base):
    """Every note is anchored to ayah ids — the graph is the Quran itself."""

    __tablename__ = "note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # The three visually distinct states, enforced at the data layer:
    # retrieved | system_suggested | own_note
    provenance: Mapped[str] = mapped_column(String(24), default="own_note", index=True)
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    anchors: Mapped[list[NoteAnchor]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "provenance in ('retrieved','system_suggested','own_note')", name="ck_note_provenance"
        ),
    )


class NoteAnchor(Base):
    __tablename__ = "note_anchor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("note.id", ondelete="CASCADE"), index=True)
    ayah_id: Mapped[int | None] = mapped_column(ForeignKey("ayah.id"), nullable=True, index=True)
    root_id: Mapped[int | None] = mapped_column(ForeignKey("root.id"), nullable=True, index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concept.id"), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    note: Mapped[Note] = relationship(back_populates="anchors")


class Hypothesis(Base):
    """Believed -> tested -> abandoned, with the reason recorded."""

    __tablename__ = "hypothesis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    statement: Mapped[str] = mapped_column(Text)  # natural language, Urdu or English
    language: Mapped[str] = mapped_column(String(8), default="ur")
    compiled_query: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="believed", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("hypothesis.id"), nullable=True)
    abandoned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    runs: Mapped[list[HypothesisRun]] = relationship(back_populates="hypothesis")

    __table_args__ = (
        CheckConstraint(
            "status in ('believed','testing','tested','supported','refuted','abandoned')",
            name="ck_hypothesis_status",
        ),
    )


class HypothesisRun(Base):
    __tablename__ = "hypothesis_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypothesis.id"), index=True)
    compiled_query: Mapped[dict] = mapped_column(JSONType, default=dict)
    supporting: Mapped[list] = mapped_column(JSONType, default=list)  # ayah ids
    violating: Mapped[list] = mapped_column(JSONType, default=list)  # ayah ids
    coverage: Mapped[float] = mapped_column(Float, default=0.0)
    statistics: Mapped[dict] = mapped_column(JSONType, default=dict)
    verdict: Mapped[str] = mapped_column(String(24), default="inconclusive")
    created_at: Mapped[datetime] = _now()

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="runs")


class Finding(Base):
    """Librarian's memory: what the team already researched."""

    __tablename__ = "finding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    ayah_ids: Mapped[list] = mapped_column(JSONType, default=list)
    root_ids: Mapped[list] = mapped_column(JSONType, default=list)
    citations: Mapped[list] = mapped_column(JSONType, default=list)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # dedupe key
    review_status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()


class ResearchRun(Base):
    """One agent run: durable state for LangGraph checkpointing + LangFuse id."""

    __tablename__ = "research_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # Wide enough for the "running:<agent>" checkpoint states.
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    ledger: Mapped[dict] = mapped_column(JSONType, default=dict)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_ceiling_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # incomplete means the ceiling stopped it: partial results, never a
    # fabricated completion (WP-05).
    incomplete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TopicRegistration(Base):
    """Shared topic registry — stops two researchers doing the same work."""

    __tablename__ = "topic_registration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(512))
    slug: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _now()


class IngestLog(Base):
    """Provenance for the corpus itself: what was loaded, from where, when."""

    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _now()


# ---------------------------------------------------------------------------
# WP-01/WP-53: identity, roles and tenancy
# ---------------------------------------------------------------------------


class Organisation(Base):
    """A tenant. Corpus data is shared; everything user-generated is scoped here."""

    __tablename__ = "organisation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    # local_only refuses every hosted provider call — some institutions cannot
    # send text to third parties at all (WP-12).
    privacy_mode: Mapped[str] = mapped_column(String(16), default="standard")
    model_policy: Mapped[dict] = mapped_column(JSONType, default=dict)
    monthly_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint("privacy_mode in ('standard','local_only')", name="ck_org_privacy"),
    )


class ApiKeyRecord(Base):
    """Bring-your-own-key storage (WP-12).

    Ciphertext only. No endpoint returns it, no log records it; the plaintext
    exists in memory for the duration of one provider call.
    """

    __tablename__ = "api_key_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(16))  # last 4 + hash, for display
    created_at: Mapped[datetime] = _now()

    __table_args__ = (UniqueConstraint("org_id", "user_id", "provider", name="uq_api_key"),)


# ---------------------------------------------------------------------------
# WP-05/WP-06: cost governance and caching
# ---------------------------------------------------------------------------


class UsageRecord(Base):
    """One model call's cost, attributed to a run, a user and an org."""

    __tablename__ = "usage_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organisation.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()


class CacheEntry(Base):
    """Content-addressed cache for model calls and expensive analytics (WP-06).

    Deterministic retrieval is deliberately not cached: the SQL is cheaper than
    the cache lookup would be.
    """

    __tablename__ = "cache_entry"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    value: Mapped[dict] = mapped_column(JSONType)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _now()
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Layer 6: the commons — shared research, discussion, signals
# ---------------------------------------------------------------------------
#
# A feed over a religious corpus is where fabricated scripture would enter if
# anywhere did, so posts and comments run through exactly the same renderer and
# scripture guard as agent output: quotations are placeholders resolved from the
# database, and raw Arabic that appears in no corpus row is refused at write
# time. Nothing here is a softer path into the app than the agents get.
#
# The other rule this schema encodes: a vote is a *popularity* signal and is
# stored apart from the *evidence* signals (attached findings, verified
# citations, a hypothesis verdict). The feed may sort by the former; it may
# never let the former overwrite the latter. An upvoted post whose attached
# hypothesis was refuted still reads "refuted".


class Post(Base):
    """One shared piece of research or discussion."""

    __tablename__ = "post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), nullable=True, index=True
    )
    org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisation.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    # The author's template: scripture appears as {{ayah:2:255}} placeholders,
    # never as typed Arabic. `body_rendered` is the resolved text, cached so the
    # feed does not re-render 50 posts per request.
    body: Mapped[str] = mapped_column(Text)
    body_rendered: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    # question | insight | finding | hypothesis | correction
    kind: Mapped[str] = mapped_column(String(16), default="insight", index=True)

    # Evidence attachments. A post carrying one of these is badged differently
    # from a bare opinion, and renders that object's real citations.
    finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("finding.id"), nullable=True, index=True
    )
    hypothesis_id: Mapped[int | None] = mapped_column(
        ForeignKey("hypothesis.id"), nullable=True, index=True
    )
    note_id: Mapped[int | None] = mapped_column(ForeignKey("note.id"), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Corpus anchors, so a post surfaces on the ayah and root pages it is about.
    ayah_ids: Mapped[list] = mapped_column(JSONType, default=list)
    roots: Mapped[list] = mapped_column(JSONType, default=list)
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    # Citations resolved at write time — the same payloads the renderer produced.
    citations: Mapped[list] = mapped_column(JSONType, default=list)

    # visible | hidden | removed. Hidden is a reviewer action pending appeal;
    # removed is final. Neither deletes the row: moderation has to be auditable.
    status: Mapped[str] = mapped_column(String(16), default="visible", index=True)
    moderated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    moderation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Denormalised counters. Recomputed from the vote/comment tables on write —
    # the feed reads them, nothing trusts them as the source of truth.
    upvotes: Mapped[int] = mapped_column(Integer, default=0, index=True)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    flag_count: Mapped[int] = mapped_column(Integer, default=0, index=True)

    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    comments: Mapped[list[Comment]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "kind in ('question','insight','finding','hypothesis','correction')",
            name="ck_post_kind",
        ),
        CheckConstraint(
            "status in ('visible','hidden','removed')", name="ck_post_status"
        ),
        Index("ix_post_feed", "status", "created_at"),
        Index("ix_post_useful", "status", "upvotes"),
    )


class Comment(Base):
    """A reply. Threaded one level deep by ``parent_id``."""

    __tablename__ = "post_comment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("post.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("post_comment.id", ondelete="CASCADE"), nullable=True, index=True
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text)
    body_rendered: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    citations: Mapped[list] = mapped_column(JSONType, default=list)

    status: Mapped[str] = mapped_column(String(16), default="visible", index=True)
    moderated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    moderation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    flag_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = _now()
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    post: Mapped[Post] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship(foreign_keys=[author_id])

    __table_args__ = (
        CheckConstraint(
            "status in ('visible','hidden','removed')", name="ck_comment_status"
        ),
    )


class Vote(Base):
    """An upvote. There is no downvote, deliberately.

    A downvote on a scholarly claim is a popularity verdict wearing the costume
    of a correctness verdict, and on this corpus it would bury well-evidenced
    minority positions. Disagreement belongs in a comment or a `correction`
    post, where it has to be argued and can itself be checked.
    """

    __tablename__ = "post_vote"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # post | comment
    target_kind: Mapped[str] = mapped_column(String(8), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("target_kind", "target_id", "user_id", name="uq_vote_once"),
        CheckConstraint("target_kind in ('post','comment')", name="ck_vote_target"),
    )


class Flag(Base):
    """A report. Posting is immediate, so this is the whole safety net."""

    __tablename__ = "post_flag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(8), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    # fabricated_scripture | misattribution | off_topic | abuse | other
    reason: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open | upheld | dismissed
    resolution: Mapped[str] = mapped_column(String(16), default="open", index=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint(
            "target_kind", "target_id", "reporter_id", name="uq_flag_once_per_reporter"
        ),
        CheckConstraint("target_kind in ('post','comment')", name="ck_flag_target"),
        CheckConstraint(
            "resolution in ('open','upheld','dismissed')", name="ck_flag_resolution"
        ),
    )


class AsbabReport(Base):
    """An occasion-of-revelation *report* (WP-20).

    Deliberately not a tafsir row and deliberately not a property of an ayah.
    An asbab entry is a claim someone transmitted — "this was revealed when X
    happened" — and the scholarly tradition disagrees about many of them. Filing
    them as commentary makes them read as settled context, which is the single
    thing the interviewed researchers drew a red line around.

    So every row carries a claimant and a grade, and ``grade`` has no default
    that could be mistaken for authentication: an ungraded report says
    ``ungraded``, loudly, and the API refuses to serialise a row without it.

    ``mapping`` records how the ayah was determined, because in the shipped
    al-Wahidi edition the upstream filing was wrong for 673 of 690 entries —
    the verse the report is *about* is cited inside its own text, and that is
    the reference this table trusts.
    """

    __tablename__ = "asbab_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id"), index=True)
    ayah_id: Mapped[int | None] = mapped_column(
        ForeignKey("ayah.id"), nullable=True, index=True
    )
    surah_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ayah_num: Mapped[int | None] = mapped_column(Integer, nullable=True)

    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # Who transmitted or compiled the report.
    claimant: Mapped[str] = mapped_column(String(256))
    source_work: Mapped[str] = mapped_column(String(256))
    reference: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # sahih | hasan | daif | mursal | ungraded — never nullable, never defaulted
    # to anything that reads as authenticated.
    grade: Mapped[str] = mapped_column(String(24), default="ungraded", index=True)
    graded_by: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # in_text_reference | upstream_filing | unmapped
    mapping: Mapped[str] = mapped_column(String(32), default="unmapped", index=True)
    mapping_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Entries that are not occasion-of-revelation reports at all are kept but
    # withheld: the row survives so the discrepancy stays auditable.
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    withheld_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(
            "grade in ('sahih','hasan','daif','mursal','ungraded')", name="ck_asbab_grade"
        ),
        CheckConstraint(
            "status in ('published','withheld')", name="ck_asbab_status"
        ),
        Index("ix_asbab_lookup", "ayah_id", "status"),
    )
