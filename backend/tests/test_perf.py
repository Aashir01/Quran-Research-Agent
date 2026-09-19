"""Performance budgets (Track H).

Not benchmarks — budgets. A benchmark records how fast something was; a budget
fails the build when a change makes it slow enough to alter how the tool is
used. Every number here is deliberately loose, set well above the measured
time, because a budget tuned to the current timing fails on a noisy CI box and
gets deleted within a month.

Two of these guard specific regressions that already happened once:

* Grammar search over a multi-pattern query took 92 seconds before the ayah
  ordinal was materialised at ingest. That is not "slow", it is a different
  product — nobody explores interactively at 92 seconds a query.
* The common-link null model rescanned 163k chain positions on every call, at
  16 seconds each.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest


@contextmanager
def budget(seconds: float, what: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    assert elapsed < seconds, (
        f"{what} took {elapsed:.2f}s, over its {seconds:.0f}s budget. "
        "The budget is loose on purpose; crossing it means something changed in kind."
    )


def test_exhaustive_root_count_is_interactive(session):
    from qra import tools

    with budget(2.0, "exhaustive count over a 854-occurrence root"):
        payload = tools.count_occurrences(session, root="علم")
    assert payload["total_occurrences"] > 800


def test_phrase_search_is_interactive(session):
    from qra import tools

    with budget(2.0, "exact phrase search"):
        tools.search_phrase(session, phrase="الرحمن الرحيم", limit=50)


def test_grammar_search_stays_out_of_the_92_second_hole(session):
    """The regression this budget exists for. Before `Segment.ayah_index` was
    materialised at ingest, a two-pattern query ran a window function per alias
    and took 92 seconds."""
    from qra.analytics import grammar

    with budget(5.0, "two-pattern grammar query"):
        result = grammar.run(session, "V:IMPV P", limit=20)
    assert result["total_matches"] > 0


def test_a_single_pattern_query_is_fast(session):
    from qra.analytics import grammar

    with budget(3.0, "single-pattern grammar query"):
        grammar.run(session, "V:IMPV", limit=20)


def test_the_common_link_null_model_uses_its_cache(session):
    """The corpus scan behind the null model is 163k rows. Rescanning it per
    call put 16 seconds on every common-link request."""
    from sqlalchemy import select

    from qra.analytics import rijal
    from qra.models import ChainPosition, Narrator

    if not session.scalar(select(Narrator.id).limit(1)):
        pytest.skip("transmission graph not built")

    ids = list(session.scalars(select(ChainPosition.hadith_id).distinct().limit(6)).all())
    rijal._corpus_chains(session)  # warm, as a running process would be
    with budget(4.0, "common-link with its null model"):
        rijal.common_link(session, ids, trials=200)


def test_the_stylometry_sweep_is_not_quadratic(session):
    """114 surah profiles are built from two queries and a pass over the words.
    A per-surah query would be 114 round trips and this would notice."""
    from qra.analytics import textscience

    with budget(6.0, "per-surah style profiles for the whole corpus"):
        profiles = textscience.profiles(session)
    assert len(profiles) == 114


def test_the_makki_madani_comparison_is_interactive(session):
    from qra.analytics import textscience

    with budget(6.0, "six-measure Makki/Madani comparison"):
        textscience.makki_madani(session)


def test_the_conflation_report_is_interactive(session):
    from sqlalchemy import select

    from qra.analytics import rijal
    from qra.models import Narrator

    if not session.scalar(select(Narrator.id).limit(1)):
        pytest.skip("transmission graph not built")
    with budget(3.0, "conflation report over 20k names"):
        rijal.conflation_report(session, limit=25)


def test_the_whole_red_team_suite_runs_quickly(session):
    """It should be cheap enough to run on every deploy. A suite that takes
    minutes is a suite that gets run quarterly."""
    from qra.redteam import run_redteam

    with budget(10.0, "the red-team suite"):
        report = run_redteam(session)
    assert report["clean"]
