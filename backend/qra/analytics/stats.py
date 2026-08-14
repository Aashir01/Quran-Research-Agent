"""Statistical honesty layer.

This is the module that decides whether a "pattern" is allowed to be called a
pattern. Every analytic in this package routes its headline number through
here, and the result carries:

* the **expected** value under an explicit chance model,
* an **effect size**, not just a p-value,
* a **multiple-comparison** correction whenever more than one hypothesis was
  tested in the same sweep,
* an explicit ``within_chance`` flag when the observation is unremarkable.

Numerology works by reporting the numerator and hiding the denominator. The
antidote is to make the denominator structural: you cannot get a number out of
this system without also getting what it would have been by chance.

Pure ``math`` — no scipy — so results are identical everywhere and the
arithmetic is auditable line by line.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

ALPHA = 0.05


@dataclass
class Significance:
    observed: float
    expected: float
    n: int
    p_value: float
    effect_size: float
    effect_measure: str
    test: str
    within_chance: bool
    direction: str  # more | fewer | as_expected
    interpretation: str
    corrected_p: float | None = None
    correction: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Distributions (log-space so 6,236-choose-k does not explode)
# ---------------------------------------------------------------------------


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )


def binomial_tail(k: int, n: int, p: float, *, upper: bool) -> float:
    """P(X >= k) or P(X <= k) for X ~ Binomial(n, p)."""
    if n <= 0:
        return 1.0
    k = max(0, min(k, n))
    rng = range(k, n + 1) if upper else range(0, k + 1)
    total = 0.0
    for i in rng:
        total += math.exp(_log_binom_pmf(i, n, p))
    return min(1.0, max(0.0, total))


def binomial_test(k: int, n: int, p: float) -> tuple[float, str]:
    """Two-sided exact binomial test. Returns (p_value, direction)."""
    if n <= 0:
        return 1.0, "as_expected"
    expected = n * p
    if k > expected:
        return min(1.0, 2 * binomial_tail(k, n, p, upper=True)), "more"
    if k < expected:
        return min(1.0, 2 * binomial_tail(k, n, p, upper=False)), "fewer"
    return 1.0, "as_expected"


def chi2_sf_1df(x: float) -> float:
    """Survival function of chi-square with 1 degree of freedom."""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


def poisson_tail_upper(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam), used for rare co-occurrence counts."""
    if lam <= 0:
        return 1.0 if k <= 0 else 0.0
    # 1 - P(X <= k-1)
    total = 0.0
    term = math.exp(-lam)
    for i in range(0, k):
        if i > 0:
            term *= lam / i
        total += term
    return min(1.0, max(0.0, 1.0 - total))


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def assess(
    observed: int,
    n: int,
    baseline_rate: float,
    *,
    test: str = "binomial",
    alpha: float = ALPHA,
    label: str = "observation",
) -> Significance:
    """Compare an observed count against an explicit chance baseline.

    ``baseline_rate`` is the probability of a hit under the null model the
    caller must name — usually "this root's overall corpus rate" or "this
    concept's share of ayat". Making the caller supply it is the point: an
    analytic that cannot state its null model has no business reporting a
    finding.
    """
    expected = n * baseline_rate
    p_value, direction = binomial_test(observed, n, baseline_rate)

    # Effect size: risk ratio against the baseline, plus Cohen's h so tiny
    # absolute differences on huge n cannot masquerade as important.
    rate = observed / n if n else 0.0
    ratio = (rate / baseline_rate) if baseline_rate > 0 else math.inf
    h = 2 * math.asin(math.sqrt(min(1.0, rate))) - 2 * math.asin(
        math.sqrt(min(1.0, baseline_rate))
    )

    warnings: list[str] = []
    if n < 20:
        warnings.append(
            f"Only {n} trials — this cannot support a claim about the corpus, "
            "however striking the ratio looks."
        )
    if expected < 5:
        warnings.append(
            f"Expected count under the null is {expected:.2f} (<5); small-count "
            "artefacts dominate here."
        )
    if abs(h) < 0.2 and p_value < alpha:
        warnings.append(
            "Statistically distinguishable from chance but the effect is small "
            "(Cohen's h < 0.2) — significance here is a function of corpus size."
        )

    within_chance = p_value >= alpha
    if within_chance:
        interpretation = (
            f"{label}: {observed} observed vs {expected:.1f} expected by chance "
            f"(p={p_value:.3f}). This is within the range chance produces — it is not a pattern."
        )
    else:
        interpretation = (
            f"{label}: {observed} observed vs {expected:.1f} expected "
            f"({ratio:.2f}× baseline, p={p_value:.2e}). Distinguishable from chance"
            + (" but small in size." if abs(h) < 0.2 else ".")
        )

    return Significance(
        observed=observed,
        expected=round(expected, 3),
        n=n,
        p_value=p_value,
        effect_size=round(ratio, 3) if ratio != math.inf else float("inf"),
        effect_measure=f"risk_ratio (Cohen's h={h:.3f})",
        test=test,
        within_chance=within_chance,
        direction=direction,
        interpretation=interpretation,
        warnings=warnings,
    )


def correct_multiple(
    results: list[Significance], *, method: str = "benjamini_hochberg", alpha: float = ALPHA
) -> list[Significance]:
    """Apply a multiple-comparison correction across a family of tests.

    Any sweep that tests many roots, many surahs or many pairs *must* pass its
    results through this. Testing 1,651 roots at p<0.05 yields ~83 "findings"
    from noise alone; that is exactly how numerological claims get manufactured.
    """
    if not results:
        return results
    m = len(results)
    order = sorted(range(m), key=lambda i: results[i].p_value)

    if method == "bonferroni":
        for i in order:
            results[i].corrected_p = min(1.0, results[i].p_value * m)
    else:
        method = "benjamini_hochberg"
        prev = 1.0
        for rank, idx in enumerate(reversed(order), start=1):
            i = m - rank + 1  # BH rank, largest p first
            adjusted = min(prev, results[idx].p_value * m / i)
            results[idx].corrected_p = adjusted
            prev = adjusted

    for result in results:
        result.correction = f"{method} over {m} tests"
        was_within = result.within_chance
        result.within_chance = (result.corrected_p or 1.0) >= alpha
        if result.within_chance and not was_within:
            result.warnings.append(
                f"Significant on its own (p={result.p_value:.4f}) but not after correcting "
                f"for {m} simultaneous tests (adjusted p={result.corrected_p:.4f}). "
                "Treat as noise unless it was predicted in advance."
            )
            result.interpretation += " Does not survive multiple-comparison correction."
    return results


def sweep_warning(n_tests: int, *, prespecified: bool = False) -> str | None:
    if prespecified or n_tests <= 1:
        return None
    expected_false = n_tests * ALPHA
    return (
        f"{n_tests} hypotheses tested in this sweep. At α={ALPHA}, roughly "
        f"{expected_false:.0f} would clear the bar by chance alone. Corrected p-values "
        "are reported alongside raw ones; a finding you did not predict in advance "
        "needs the corrected column."
    )


def numerology_guard(counts: dict[str, int], *, corpus_total: int) -> list[str]:
    """Flag the shapes numerological claims usually take.

    Not a p-value — a set of structural warnings about the *form* of a claim,
    which is where most such claims fail long before the statistics.
    """
    notes = []
    for label, value in counts.items():
        if value in (7, 19, 40, 99, 114, 786):
            notes.append(
                f"'{label}' = {value}, a number with pre-existing cultural weight. "
                "A count is only evidence if the counting rule was fixed before the count "
                "was seen — state the rule, then check it survives on a different edition, "
                "orthography and root list."
            )
    if corpus_total:
        for label, value in counts.items():
            if value and corpus_total / value in (7, 19, 114):
                notes.append(
                    f"'{label}' divides the corpus total evenly — check this is not an "
                    "artefact of how the denominator was chosen."
                )
    notes.append(
        "Orthography matters: counts of letters or words change between Uthmani and "
        "Imlaei scripts and between root lists. Report which edition and which "
        "morphological source produced the number."
    )
    return notes
