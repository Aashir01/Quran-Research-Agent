"""The workbench's falsification-first contract."""

import pytest

from qra.analytics.hypothesis import compile_hypothesis, run_hypothesis


def test_urdu_claim_compiles_to_the_right_shape(session):
    spec = compile_hypothesis(session, "Quran mein sabr hamesha salah ke saath aata hai", language="ur")
    assert spec.claim_type == "always_with"
    assert spec.subject.value == "sabr"
    assert spec.object is not None and spec.object.value == "salah"
    assert spec.scope == "ayah"


def test_english_claim_compiles(session):
    spec = compile_hypothesis(session, "ilm mostly appears with hidayah in the same ayah", language="en")
    assert spec.claim_type == "mostly_with"
    assert {spec.subject.value, spec.object.value} == {"ilm", "hidayah"}


def test_never_claim_inverts_support_and_violation(session):
    spec = compile_hypothesis(session, "sabr kabhi salah ke saath nahi aata", language="ur")
    assert spec.claim_type == "never_with"
    result = run_hypothesis(session, spec, sample=5)
    # Co-occurrences exist, so a "never" claim must be refuted by them.
    assert result.verdict == "refuted"
    assert result.violating_count > 0


def test_makki_madani_claim_becomes_a_distribution_test(session):
    spec = compile_hypothesis(session, "Taqwa aksar makki surahon mein aata hai", language="ur")
    assert spec.claim_type in ("mostly_with", "distribution")
    assert spec.filters.get("revelation_place") == "makki"


def test_one_counter_example_refutes_an_always_claim(session):
    spec = compile_hypothesis(session, "Quran mein sabr hamesha salah ke saath aata hai", language="ur")
    result = run_hypothesis(session, spec, sample=5)
    assert result.verdict == "refuted"
    assert result.violating_count > 0
    assert "does not survive a single exception" in result.headline


def test_violations_are_serialised_before_supporting_evidence(session):
    """Ordering is part of the contract, not a rendering preference."""
    spec = compile_hypothesis(session, "Quran mein sabr hamesha salah ke saath aata hai", language="ur")
    payload = run_hypothesis(session, spec, sample=3).to_dict()
    keys = list(payload)
    assert keys.index("violating") < keys.index("supporting")
    assert keys.index("violating_count") < keys.index("supporting_count")


def test_result_always_reports_the_chance_baseline(session):
    spec = compile_hypothesis(session, "Quran mein sabr hamesha salah ke saath aata hai", language="ur")
    result = run_hypothesis(session, spec, sample=3)
    assert "baseline_rate" in result.statistics
    assert "null_model" in result.statistics
    assert result.statistics["expected"] >= 0


def test_coverage_and_universe_are_consistent(session):
    spec = compile_hypothesis(session, "Quran mein sabr hamesha salah ke saath aata hai", language="ur")
    result = run_hypothesis(session, spec, sample=3)
    assert result.supporting_count + result.violating_count == result.universe_size
    assert result.coverage == pytest.approx(result.supporting_count / result.universe_size)


def test_unresolvable_claim_fails_loudly(session):
    with pytest.raises(ValueError):
        compile_hypothesis(session, "this claim names nothing in the corpus", language="en")


def test_compiled_query_is_inspectable(session):
    spec = compile_hypothesis(session, "Quran mein sabr hamesha salah ke saath aata hai", language="ur")
    payload = spec.to_dict()
    assert payload["subject"]["roots"]
    assert payload["compiled_by"] == "rule_based"
    assert isinstance(payload["notes"], list)
