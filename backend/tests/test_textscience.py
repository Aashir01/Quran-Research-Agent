"""Quantitative text science (Track J).

Mathematics applied to the Qur'an, which means mathematics applied to *a text*:
how predictable its word sequence is, how its vocabulary renews itself, how its
verses rhyme. Real numbers, falsifiable, and none of them a fact about physics.

Most of these tests guard one failure mode, because it has already bitten this
module three times: **a statistic that is secretly a measure of length**. Raw
type-token ratio falls as text lengthens. Share-of-verses-sharing-the-commonest
ending falls as a surah lengthens. Entropy rises with sample size. Each would
have produced a confident, publishable, wrong comparison.
"""

from __future__ import annotations

from collections import Counter

import pytest

from qra.analytics import textscience as ts
from qra.analytics.textscience import TextScienceError

# --- the maths, against values that can be checked by hand ------------------


def test_entropy_of_a_fair_coin_is_one_bit():
    assert ts.shannon(Counter({"h": 50, "t": 50})) == pytest.approx(1.0)
    assert ts.shannon(Counter({"a": 1})) == pytest.approx(0.0)
    # Four equiprobable symbols carry two bits.
    assert ts.shannon(Counter({c: 10 for c in "abcd"})) == pytest.approx(2.0)


def test_the_t_distribution_matches_published_critical_values():
    """Implemented here because the project carries no scipy, so it has to be
    checked against the table rather than trusted."""
    assert 2 * ts._t_sf(2.228, 10) == pytest.approx(0.05, abs=1e-3)
    assert 2 * ts._t_sf(3.169, 10) == pytest.approx(0.01, abs=1e-3)
    # Large df converges on the normal.
    assert 2 * ts._t_sf(1.96, 1e6) == pytest.approx(0.05, abs=1e-3)
    assert 2 * ts._t_sf(0.0, 10) == pytest.approx(1.0)


def test_welch_reports_an_effect_size_beside_every_p():
    """On 92 surahs a negligible difference clears significance easily, so a p
    without a d is a number that cannot be read."""
    result = ts._welch([1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0])
    assert result["p_value"] < 0.05
    assert result["cohens_d"] is not None
    assert result["cohens_d"] < 0


def test_yules_k_is_far_more_length_stable_than_the_type_token_ratio():
    """The claim the module actually relies on, stated as a comparison.

    Yule's K is *asymptotically* length-independent, not exactly so — it carries
    a small-sample term — and over a tenfold change in length it moves a few
    per cent. The type-token ratio over the same change moves by a factor of
    ten. That gap is why one is compared across surahs and the other is only
    reported.
    """
    unit = ["a", "b", "c", "a", "d"]
    short, long = unit * 20, unit * 200

    k_drift = abs(ts._yules_k(Counter(long)) - ts._yules_k(Counter(short))) / ts._yules_k(
        Counter(short)
    )
    ttr_short = len(set(short)) / len(short)
    ttr_long = len(set(long)) / len(long)
    ttr_drift = abs(ttr_long - ttr_short) / ttr_short

    assert k_drift < 0.05
    assert ttr_drift > 0.8
    assert ttr_drift > k_drift * 10


def test_mattr_is_stable_where_raw_ttr_is_not():
    unit = ["a", "b", "c", "d", "e", "f"]
    assert ts._mattr(unit * 20) == pytest.approx(ts._mattr(unit * 200), rel=0.05)


def test_zipf_recovers_a_planted_slope():
    """A synthetic corpus with a known exponent must come back with it."""
    counts = Counter({f"w{rank}": int(100_000 / rank) for rank in range(1, 400)})
    fit = ts._zipf_fit(counts)
    assert fit["slope"] == pytest.approx(-1.0, abs=0.05)
    assert fit["r_squared"] > 0.98


def test_the_fasila_is_the_final_consonants():
    assert ts.fasila("قل هو الله احد") == "حد"
    assert ts.fasila("") == ""


# --- against the corpus -----------------------------------------------------


def test_the_control_corpus_has_its_chains_stripped(session):
    """A chain of transmission is formulaic by construction — the same two dozen
    names over tens of thousands of narrations. Leaving it in depresses the
    control's entropy and makes the Qur'an look more varied than ordinary Arabic
    for reasons of genre. Stripping it raised the control's vocabulary by a
    fifth, so the confound was real."""
    with_isnad, _ = ts._hadith_tokens(session, limit=800, matn_only=False)
    matn_only, _ = ts._hadith_tokens(session, limit=800, matn_only=True)
    assert len(set(matn_only)) / len(matn_only) > len(set(with_isnad)) / len(with_isnad)


def test_the_control_is_truncated_to_the_same_length(session):
    """Entropy grows with sample size, so an unmatched comparison measures
    corpus length and nothing else."""
    payload = ts.information(session)
    assert payload["control"]["words"] == payload["quran"]["words"]
    assert "isnad" in payload["control"]["corpus"]


def test_letter_entropy_is_near_identical_across_the_two_corpora(session):
    """Both are Arabic in the same script. A large gap here would mean the
    measurement is broken, not that the Qur'an is unusual."""
    payload = ts.information(session)
    quran = payload["quran"]["letter_entropy_bits"]
    control = payload["control"]["letter_entropy_bits"]
    assert abs(quran - control) < 0.3


def test_both_corpora_sit_near_a_zipf_slope_of_minus_one(session):
    """Which is exactly why 'the Qur'an follows Zipf's law' is a fact about
    language rather than about the Qur'an — and the payload says so."""
    payload = ts.information(session)
    assert -1.3 < payload["quran"]["zipf"]["slope"] < -0.7
    assert -1.3 < payload["control"]["zipf"]["slope"] < -0.7
    assert "fact about language" in payload["reading"]


# --- the Makki/Madani comparison -------------------------------------------


def test_ayah_length_separates_makki_from_madani(session):
    """The strongest measurable form of a commonplace: Madinan verses run to
    roughly twice the length. If this came out flat the module would be
    measuring nothing."""
    result = ts.makki_madani(session)
    row = next(m for m in result["measures"] if m["measure"] == "mean_ayah_words")
    assert row["survives_correction"] is True
    assert row["mean_b"] > row["mean_a"] * 1.5
    assert abs(row["cohens_d"]) > 0.8


def test_the_comparison_corrects_across_the_whole_family(session):
    result = ts.makki_madani(session)
    assert "would clear p<0.05 by chance alone" in result["headline"]
    assert result["correction"].startswith("benjamini_hochberg")
    for row in result["measures"]:
        if row["p_value"] is not None:
            assert "bh_threshold" in row


def test_every_compared_measure_is_length_robust(session):
    """Raw TTR is reported on the profile and must not be one of the measures
    compared: comparing al-Baqara with al-Kawthar on it measures length and
    calls the result style."""
    compared = {key for key, _ in ts.MEASURES}
    assert "type_token_ratio" not in compared
    assert "mattr" in compared and "yules_k" in compared
    assert "length-robust" in ts.makki_madani(session)["measurement_note"]


def test_a_negative_result_is_reported_as_one(session):
    """Rhyme concentration shows no Makki/Madani difference, against a common
    claim that it should. A module that only ever confirms is not measuring."""
    result = ts.makki_madani(session)
    row = next(m for m in result["measures"] if m["measure"] == "rhyme_concentration")
    assert row["survives_correction"] is False
    assert abs(row["cohens_d"]) < 0.3


def test_the_traditional_attribution_is_flagged_as_traditional(session):
    result = ts.makki_madani(session)
    assert "disputed" in result["caveat"]


# --- trends and prosody -----------------------------------------------------


def test_ayah_length_rises_across_the_revelation_order(session):
    trend = ts.nuzul_trend(session, "mean_ayah_words")
    assert trend["spearman_rho"] > 0.4
    assert trend["p_value"] < 0.001
    assert "Spearman" in trend["method"]
    assert "reconstruction" in trend["caveat"]


def test_an_unknown_measure_is_refused(session):
    with pytest.raises(TextScienceError, match="measure must be one of"):
        ts.nuzul_trend(session, "not_a_measure")


def test_the_rhyme_ranking_is_not_just_a_ranking_of_short_surahs(session):
    """Share-of-commonest-ending falls with length, so ranking on it puts the
    shortest surahs on top for being short. Concentration is normalised against
    the maximum entropy a surah of that length could have."""
    top = ts.prosody(session, limit=12)["most_consistent"]
    assert any(row["ayat"] > 100 for row in top), [r["ayat"] for r in top]


def test_the_commonest_endings_are_the_known_ones(session):
    """ون and ين dominate Qur'anic rhyme. A different answer means the fasila
    extraction is wrong."""
    endings = [e["ending"] for e in ts.prosody(session)["commonest_endings"][:4]]
    assert "ون" in endings
    assert "ين" in endings


def test_surah_114_rhymes_perfectly(session):
    """An-Nas ends every verse in -as. A check with an answer known in advance."""
    profile = next(p for p in ts.profiles(session) if p.surah == 114)
    assert profile.rhyme_concentration == pytest.approx(1.0)


def test_prosody_admits_it_measures_orthography(session):
    """Qur'anic rhyme is a property of recitation — pausal forms change endings —
    and this reads the written form."""
    assert "recitation" in ts.prosody(session)["caveat"]


def test_the_module_states_what_it_is_not_measuring(session):
    scope = ts.summary(session)["scope"]
    assert "Nothing here is a claim about the physical world" in scope
    assert "facts about itself and not about nature" in scope
