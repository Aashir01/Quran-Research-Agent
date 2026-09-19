"""Objection generation (Track E).

The Critic asks whether a claim is supported. This asks what the strongest case
against it is, which is a different and harder question — the failure mode of a
research tool is rarely a claim with no evidence, it is a claim with real
evidence and an unexamined alternative.

Every objection must be *computed*. An LLM asked to be sceptical produces
objections shaped like objections; these have to produce numbers.
"""

from __future__ import annotations

from qra.analytics.objections import objections
from qra.analytics.stats import assess


def test_a_within_chance_count_draws_a_fatal_objection(session):
    result = objections(
        session,
        claim="sabr clusters with salah",
        significance=assess(12, 100, 0.11).to_dict(),
    )
    base = next(o for o in result["objections"] if o["kind"] == "base_rate")
    assert base["severity"] == "fatal"
    assert result["fatal"] >= 1
    assert "does not survive" in result["verdict"]


def test_a_significant_but_negligible_effect_is_objected_to(session):
    """On a corpus this size a difference too small to matter clears p<0.05
    easily, so significance alone is not the finding."""
    result = objections(
        session, claim="x differs from y", significance=assess(5200, 10000, 0.51).to_dict()
    )
    kinds = {o["kind"] for o in result["objections"]}
    assert "base_rate" in kinds


def test_a_polysemous_root_is_flagged_with_its_other_senses(session):
    """أنزل is used of scripture, rain, cattle and clothing. A claim needing one
    sense is choosing it over the others, and the objection has to show them."""
    result = objections(session, claim="nazala means physical descent", roots=["نزل"])
    objection = next(o for o in result["objections"] if o["kind"] == "polysemy")
    lemmas = {row["lemma"] for row in objection["evidence"]["lemmas"]}
    assert len(lemmas) >= 3
    assert objection["evidence"]["total"] > 250
    assert objection["survives_if"]


def test_a_universal_claim_is_told_it_is_decidable(session):
    """A universal claim over a closed corpus is not arguable — it is checkable,
    and until it is checked it is an assertion about 6,236 verses."""
    result = objections(session, claim="sabr always appears with salah", roots=["صبر"])
    objection = next(o for o in result["objections"] if o["kind"] == "universal_claim")
    assert objection["evidence"]["ayat_to_check"] > 50
    assert objection["evidence"]["first_refs"]


def test_a_length_confounded_measure_is_fatal(session):
    """Every measure on this list has produced a wrong comparison in this
    codebase at least once."""
    for measure in ("type_token_ratio", "distinct_words", "entropy", "rhyme_consistency"):
        result = objections(session, claim="a is richer than b", measure=measure)
        objection = next(o for o in result["objections"] if o["kind"] == "length_confound")
        assert objection["severity"] == "fatal", measure


def test_a_length_robust_measure_draws_no_such_objection(session):
    result = objections(session, claim="a is richer than b", measure="yules_k")
    assert not [o for o in result["objections"] if o["kind"] == "length_confound"]


def test_an_uncorrected_family_is_objected_to(session):
    result = objections(
        session,
        claim="this pairing is significant",
        significance=assess(40, 100, 0.3).to_dict(),
        comparisons_made=20,
    )
    objection = next(o for o in result["objections"] if o["kind"] == "multiple_comparisons")
    assert objection["evidence"]["comparisons"] == 20
    assert objection["evidence"]["expected_by_chance"] == 1.0


def test_a_small_sample_is_objected_to(session):
    result = objections(
        session, claim="a pattern in a small set", significance=assess(8, 10, 0.3).to_dict()
    )
    kinds = {o["kind"] for o in result["objections"]}
    assert "small_n" in kinds


def test_a_conflated_narrator_is_a_fatal_objection(session):
    """A bottleneck at a node that is several men is not a bottleneck."""
    from sqlalchemy import select

    from qra.models import Narrator

    row = session.scalar(
        select(Narrator).where(Narrator.display_name == "عبد الله")
    )
    if row is None:
        import pytest

        pytest.skip("transmission graph not built")
    result = objections(session, claim="X is the common link", narrator="عبد الله")
    objection = next(o for o in result["objections"] if o["kind"] == "conflation")
    assert objection["severity"] == "fatal"
    assert objection["evidence"]["position_spread"] >= 0.4


def test_a_same_generation_homonym_is_not_flagged_and_that_is_a_known_gap(session):
    """سفيان is two men — al-Thawri and Ibn Uyayna — and the objection does not
    fire, because they are contemporaries and the metric is generational.

    Asserted deliberately: this is the detector's documented blind spot, and a
    test that pretended otherwise would be the wrong kind of green.
    """
    from sqlalchemy import select

    from qra.models import Narrator

    row = session.scalar(select(Narrator).where(Narrator.display_name == "سفيان"))
    if row is None:
        import pytest

        pytest.skip("transmission graph not built")
    assert row.position_spread < 0.4
    result = objections(session, claim="Sufyan is the common link", narrator="سفيان")
    assert not [o for o in result["objections"] if o["kind"] == "conflation"]

    from qra.analytics import rijal

    assert "Same-generation homonyms" in rijal.conflation_report(session, limit=1)["blind_to"]


def test_objections_that_do_not_apply_are_not_raised(session):
    """A module that always returns eight objections is one whose objections
    stop being read."""
    result = objections(session, claim="a plain descriptive statement")
    assert result["objections_raised"] == 0
    assert "none of these checks applies" in result["verdict"]


def test_every_objection_says_what_would_answer_it(session):
    """An objection with no exit condition is an obstacle, not a critique."""
    result = objections(
        session,
        claim="nazala always means descent",
        roots=["نزل"],
        significance=assess(8, 10, 0.3).to_dict(),
        comparisons_made=12,
    )
    assert result["objections"]
    for objection in result["objections"]:
        assert objection["survives_if"]
        assert objection["severity"] in {"fatal", "serious", "worth_checking"}


def test_silence_is_not_endorsement(session):
    assert "silence here is not endorsement" in objections(session, claim="x")["scope"]


def test_the_effect_size_is_read_on_the_right_scale():
    """`effect_size` is a risk ratio, whose null is 1.0, not 0.0.

    Testing it against a Cohen's-h threshold called a ratio of 0.1 — a tenfold
    reduction, an enormous effect — negligible, and would have suppressed the
    objection exactly where it mattered most.
    """
    from qra.analytics.objections import _effect_magnitude

    tiny, label = _effect_magnitude(
        {"effect_measure": "risk_ratio (Cohen's h=0.020)", "effect_size": 1.02}
    )
    assert tiny == 0.02
    assert "Cohen's h" in label

    huge, _ = _effect_magnitude({"effect_measure": "risk_ratio", "effect_size": 0.1})
    assert huge > 0.5

    large, _ = _effect_magnitude(
        {"effect_measure": "risk_ratio (Cohen's h=0.85)", "effect_size": 3.1}
    )
    assert large == 0.85
