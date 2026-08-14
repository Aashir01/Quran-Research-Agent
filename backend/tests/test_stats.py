"""The statistical honesty layer, tested for the properties it promises."""

import math

import pytest

from qra.analytics.stats import (
    ALPHA,
    assess,
    binomial_tail,
    binomial_test,
    correct_multiple,
    numerology_guard,
    sweep_warning,
)


def test_binomial_tail_is_a_probability():
    assert binomial_tail(0, 10, 0.5, upper=True) == pytest.approx(1.0)
    assert 0.0 <= binomial_tail(7, 10, 0.5, upper=True) <= 1.0
    # Symmetric case: P(X>=5) + P(X<=5) = 1 + P(X=5)
    upper = binomial_tail(5, 10, 0.5, upper=True)
    lower = binomial_tail(5, 10, 0.5, upper=False)
    assert math.isclose(upper + lower - math.comb(10, 5) * 0.5**10, 1.0, abs_tol=1e-9)


def test_binomial_test_directions():
    _p, direction = binomial_test(9, 10, 0.5)
    assert direction == "more"
    _p, direction = binomial_test(1, 10, 0.5)
    assert direction == "fewer"


def test_unremarkable_observation_is_flagged_as_chance():
    result = assess(observed=50, n=100, baseline_rate=0.5, label="coin")
    assert result.within_chance is True
    assert "not a pattern" in result.interpretation


def test_striking_observation_is_not_flagged_as_chance():
    result = assess(observed=90, n=100, baseline_rate=0.5, label="loaded")
    assert result.within_chance is False
    assert result.effect_size > 1.5


def test_small_samples_get_a_warning_even_when_significant():
    result = assess(observed=5, n=5, baseline_rate=0.1, label="tiny")
    assert any("trials" in w or "Expected count" in w for w in result.warnings)


def test_large_corpus_small_effect_is_called_out():
    # 6,236 trials: a 1pp difference clears p<0.05 while meaning very little.
    result = assess(observed=530, n=6236, baseline_rate=0.08, label="big n")
    if not result.within_chance:
        assert any("small" in w.lower() for w in result.warnings)


def test_benjamini_hochberg_demotes_marginal_findings():
    # One genuinely strong result among 100 marginal ones.
    results = [assess(observed=55, n=100, baseline_rate=0.5, label=f"noise{i}") for i in range(99)]
    results.append(assess(observed=95, n=100, baseline_rate=0.5, label="real"))
    correct_multiple(results)
    assert all(r.corrected_p is not None for r in results)
    assert results[-1].within_chance is False  # the real one survives
    # Corrected p is never smaller than raw p.
    assert all(r.corrected_p >= r.p_value - 1e-12 for r in results)


def test_correction_is_monotone_in_rank():
    results = [assess(observed=k, n=100, baseline_rate=0.5, label=str(k)) for k in (95, 70, 60, 52)]
    correct_multiple(results)
    ordered = sorted(results, key=lambda r: r.p_value)
    corrected = [r.corrected_p for r in ordered]
    assert corrected == sorted(corrected)


def test_sweep_warning_names_the_expected_false_positives():
    warning = sweep_warning(1651)
    assert warning is not None
    assert f"{1651 * ALPHA:.0f}" in warning
    assert sweep_warning(1) is None


def test_numerology_guard_flags_loaded_numbers():
    notes = numerology_guard({"occurrences": 19}, corpus_total=6236)
    assert any("cultural weight" in note for note in notes)
    assert any("Orthography" in note for note in notes)
