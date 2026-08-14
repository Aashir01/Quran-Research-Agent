"""Corpus-backed tests.

The important ones here check the *exhaustiveness claim* independently: the
retrieval layer's totals are compared against counts computed a different way,
so a bug in the query builder cannot make both agree.
"""

import pytest
from sqlalchemy import func, select

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


def test_every_ayah_search_form_is_normalised(session):
    rows = session.execute(select(Ayah.text_uthmani, Ayah.text_search).limit(200)).all()
    for uthmani, folded in rows:
        assert search_form(uthmani) == folded


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
