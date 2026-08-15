"""Corpus-backed tests.

The important ones here check the *exhaustiveness claim* independently: the
retrieval layer's totals are compared against counts computed a different way,
so a bug in the query builder cannot make both agree.
"""

import pytest
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from qra.arabic import search_form
from qra.models import Ayah, Segment, Surah, Word
from qra.retrieval.base import CorpusFilter
from qra.retrieval.deterministic import (
    MorphologyFilter,
    RootQuery,
    count_occurrences,
    get_ayah,
    get_morphology,
    root_profile,
    search_phrase,
    search_root,
)


def test_corpus_shape(session):
    assert session.scalar(select(func.count()).select_from(Surah)) == 114
    assert session.scalar(select(func.count()).select_from(Ayah)) == 6236
    # The mushaf's own totals — a wrong ingest shows up here immediately.
    assert session.scalar(select(func.sum(Surah.ayah_count))) == 6236


def test_ayah_ids_are_the_canonical_mushaf_index(session):
    first = get_ayah(session, 1, 1)
    last = get_ayah(session, 114, 6)
    assert first.ayah_id == 1
    assert last.ayah_id == 6236


def test_revelation_order_is_a_permutation(session):
    orders = sorted(o for (o,) in session.execute(select(Surah.revelation_order)).all())
    assert orders == list(range(1, 115))


def test_root_search_total_matches_an_independent_count(session):
    """Exhaustiveness, verified against a differently-written query."""
    from qra.models import Root

    result = search_root(session, RootQuery(root="علم", limit=5))
    root_id = session.scalar(select(Root.id).where(Root.root == "علم"))
    direct = session.scalar(
        select(func.count()).select_from(Segment).where(Segment.root_id == root_id)
    )
    # search_root excludes prefix/suffix segments by default; the root only ever
    # sits on a stem, so the two must agree exactly.
    assert result.total_occurrences == direct
    assert result.exhaustive is True


def test_limit_does_not_change_the_totals(session):
    full = search_root(session, RootQuery(root="صبر"))
    paged = search_root(session, RootQuery(root="صبر", limit=3))
    assert paged.total_occurrences == full.total_occurrences
    assert paged.total_ayat == full.total_ayat
    assert paged.truncated is True
    assert len(paged.hits) <= 3


def test_filters_partition_the_corpus(session):
    """Makki + Madani must add back up to the whole — no ayah is in neither."""
    everything = count_occurrences(session, root="صبر", filters=CorpusFilter())
    makki = count_occurrences(session, root="صبر", filters=CorpusFilter(revelation_place="makki"))
    madani = count_occurrences(session, root="صبر", filters=CorpusFilter(revelation_place="madani"))
    assert makki["total_occurrences"] + madani["total_occurrences"] == everything["total_occurrences"]


def test_morphological_filter_narrows_not_widens(session):
    everything = search_root(session, RootQuery(root="قول"))
    imperatives = search_root(
        session,
        RootQuery(root="قول", morphology=MorphologyFilter(pos_class="V", aspect="IMPV")),
    )
    assert 0 < imperatives.total_occurrences < everything.total_occurrences


def test_makki_imperative_query_from_the_spec(session):
    """'every imperative verb from root ق-و-ل in Makki surahs' must be answerable."""
    result = search_root(
        session,
        RootQuery(
            root="ق-و-ل",
            filters=CorpusFilter(revelation_place="makki"),
            morphology=MorphologyFilter(pos_class="V", aspect="IMPV"),
            limit=5,
        ),
    )
    assert result.total_occurrences > 0
    assert all(hit.extra["revelation_place"] == "makki" for hit in result.hits)


def test_phrase_search_is_diacritic_insensitive(session):
    folded = search_phrase(session, "الرحمن الرحيم")
    exact = search_phrase(session, "ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ")
    assert folded.total_ayat == exact.total_ayat > 0


def test_phrase_totals_cover_every_match_not_just_the_page(session):
    paged = search_phrase(session, "الرحمن الرحيم", limit=2)
    full = search_phrase(session, "الرحمن الرحيم")
    assert paged.total_occurrences == full.total_occurrences
    assert paged.total_ayat == full.total_ayat


def test_word_and_segment_counts_are_in_the_expected_range(session):
    words = session.scalar(select(func.count()).select_from(Word))
    segments = session.scalar(select(func.count()).select_from(Segment))
    assert 76_000 < words < 79_000
    assert 125_000 < segments < 132_000


def test_search_key_is_built_from_the_imlaei_orthography(session):
    """The key must match what a researcher types, not the Uthmani spelling.

    Folding the Uthmani text drops the superscript alef, so ٱلۡعَٰلَمِينَ would
    key as العلمين and never match a typed العالمين.
    """
    rows = session.execute(select(Ayah.text_imlaei, Ayah.text_search).limit(300)).all()
    for imlaei, folded in rows:
        assert search_form(imlaei) == folded


def test_basmala_heading_is_not_part_of_an_opening_ayah(session):
    """The Imlaei source prefixes it to every surah's first ayah; we strip it."""
    opening = session.scalar(select(Ayah).where(Ayah.surah_id == 2, Ayah.ayah_num == 1))
    assert "بسم الله" not in opening.text_search
    # …except where the basmala genuinely is the ayah, or sits inside one.
    fatiha = session.scalar(select(Ayah).where(Ayah.surah_id == 1, Ayah.ayah_num == 1))
    sulayman = session.scalar(select(Ayah).where(Ayah.surah_id == 27, Ayah.ayah_num == 30))
    assert "بسم الله" in fatiha.text_search
    assert "بسم الله" in sulayman.text_search


def test_word_count_uses_the_corpus_word_division(session):
    """Rates per 1000 words divide segment counts by this, so it must agree."""
    rows = session.execute(
        select(Ayah.id, Ayah.word_count, func.count(Word.id))
        .join(Word, Word.ayah_id == Ayah.id)
        .group_by(Ayah.id, Ayah.word_count)
        .limit(500)
    ).all()
    assert rows
    for _aid, stored, counted in rows:
        assert stored == counted


def test_display_words_agree_with_their_morphology(session):
    """The Uthmani source splits tanwin across a space; alignment must undo it.

    Before this alignment existed, 17.6% of words showed the wrong Arabic
    beside the right analysis.
    """
    from qra.arabic import align_form
    from qra.models import Segment as Seg

    rows = session.execute(
        # The ordering inside the aggregate matters: segments concatenated out
        # of order spell a different word (ال + حمد read backwards).
        select(
            Word.id,
            Word.text,
            func.string_agg(Seg.form, aggregate_order_by(literal(""), Seg.position)),
        )
        .join(Seg, Seg.word_id == Word.id)
        .group_by(Word.id, Word.text)
        .limit(3000)
    ).all()
    mismatched = [
        (wid, text, forms)
        for wid, text, forms in rows
        if align_form(text).replace(" ", "") != align_form(forms).replace(" ", "")
    ]
    assert not mismatched, f"{len(mismatched)} words disagree with their segments"


def test_morphology_is_complete_for_an_ayah(session):
    payload = get_morphology(session, 1, 1)
    assert payload["ref"] == "1:1"
    assert len(payload["words"]) == 4
    assert payload["words"][1]["root"] is not None
    assert payload["citation"]["kind"] == "ayah"


def test_root_profile_reports_a_derivation_family(session):
    profile = root_profile(session, "صبر")
    assert profile["found"] is True
    assert profile["occurrence_count"] > 50
    assert len(profile["surface_forms"]) > 5
    assert sum(profile["by_revelation_place"].values()) == profile["occurrence_count"]


def test_unknown_root_returns_empty_not_an_error(session):
    result = search_root(session, RootQuery(root="زززز"))
    assert result.total_occurrences == 0
    assert result.hits == []


@pytest.mark.parametrize("ref", [(2, 255), (112, 1), (114, 6)])
def test_every_span_carries_a_citation(session, ref):
    span = get_ayah(session, *ref)
    assert span is not None
    assert span.citation.ref == f"{ref[0]}:{ref[1]}"
    assert span.citation.kind == "ayah"
    assert span.text


def test_known_phrase_counts(session):
    """Phrases whose counts are established independently of this system."""
    # The refrain of surah ar-Rahman.
    refrain = search_phrase(session, "فبأي آلاء ربكما تكذبان")
    assert refrain.total_ayat == 31

    # The basmala as a numbered ayah: al-Fatiha 1:1 and inside Sulayman's letter.
    basmala = search_phrase(session, "بسم الله الرحمن الرحيم")
    assert {h.ref for h in basmala.hits} == {"1:1", "27:30"}


def test_phrase_search_falls_back_to_alef_insensitive_and_says_so(session):
    """Pasting Uthmani text still finds hits — labelled, because it over-merges."""
    result = search_phrase(session, "ٱلۡعَٰلَمِينَ", limit=5)
    assert result.total_ayat > 0
    assert result.hits[0].extra["matched_tier"] == "alef_insensitive"
    assert "ALEF-INSENSITIVE" in result.description


def test_strict_tier_is_preferred_when_it_matches(session):
    result = search_phrase(session, "الحمد لله رب العالمين", limit=5)
    assert result.total_ayat == 6
    assert result.hits[0].extra["matched_tier"] == "exact"
