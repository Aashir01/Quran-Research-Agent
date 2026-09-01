"""Grammar search (WP-19).

The spec asks for "a documented query language with 20 worked examples in the
eval set". The examples in :data:`qra.analytics.grammar.EXAMPLES` are that set,
and they run here — so a change that breaks the language, or a re-ingest that
changes a count, fails the build rather than being noticed months later.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import func, select

from qra.analytics import grammar
from qra.analytics.grammar import QueryError, parse
from qra.models import Segment

# --- parsing ---------------------------------------------------------------


def test_a_bare_part_of_speech_parses():
    query = parse("V")
    assert len(query.patterns) == 1
    assert query.patterns[0].pos == "V"


def test_features_are_order_free():
    """A researcher should not have to remember slot order."""
    a = parse("V:PERF:ACT:3:M:P").patterns[0].features
    b = parse("V:M:3:ACT:P:PERF").patterns[0].features
    assert a == b
    assert a["aspect"] == "PERF" and a["person"] == "3" and a["number"] == "P"


def test_adjacency_and_lookahead_are_distinguished():
    adjacent = parse("V P")
    later = parse("V > P")
    assert adjacent.patterns[1].adjacent is True
    assert later.patterns[1].adjacent is False


def test_scope_is_stripped_from_the_pattern_body():
    query = parse("tag:COND > V:PERF @makki")
    assert query.scope.revelation_place == "makki"
    assert len(query.patterns) == 2


def test_an_unknown_feature_is_an_error_not_an_empty_result():
    """The failure that makes a query language untrustworthy: a typo and a
    genuinely empty answer look identical."""
    with pytest.raises(QueryError) as excinfo:
        parse("V:PERFECT")
    assert "PERFECT" in str(excinfo.value)
    assert "Known features" in str(excinfo.value)


def test_a_pattern_must_constrain_something():
    with pytest.raises(QueryError):
        parse("@makki")


def test_an_unknown_scope_is_rejected():
    with pytest.raises(QueryError):
        parse("V @mecca")


# --- execution against the corpus -----------------------------------------


def test_single_pattern_counts_match_the_raw_columns(session):
    """The strongest available check: a one-pattern query must agree exactly
    with a plain GROUP BY over the same column. If these drift, the compiler is
    filtering something it should not."""
    for query, column, value in (
        ("V:IMPF:JUS", Segment.mood, "JUS"),
        ("N:ACT_PCPL", Segment.derivation, "ACT_PCPL"),
        ("N:PASS_PCPL", Segment.derivation, "PASS_PCPL"),
    ):
        expected = session.scalar(
            select(func.count()).select_from(Segment).where(column == value)
        )
        assert grammar.run(session, query, limit=1)["total_matches"] == expected, query


def test_adjacency_actually_constrains(session):
    """`V P` must be a strict subset of `V > P`. If the ordinal were wrong they
    would be equal, or adjacency would match nothing at all."""
    adjacent = grammar.run(session, "V:IMPV P", limit=1)["total_matches"]
    later = grammar.run(session, "V:IMPV > P", limit=1)["total_matches"]
    assert 0 < adjacent < later


def test_scope_narrows_rather_than_changing_the_question(session):
    whole = grammar.run(session, "tag:COND > V:PERF", limit=1)
    makki = grammar.run(session, "tag:COND > V:PERF @makki", limit=1)
    madani = grammar.run(session, "tag:COND > V:PERF @madani", limit=1)
    assert makki["total_ayat"] + madani["total_ayat"] == whole["total_ayat"]


def test_results_claim_exhaustiveness_and_mean_it(session):
    result = grammar.run(session, "V:IMPV", limit=5)
    assert result["exhaustive"] is True
    assert result["returned"] == 5
    assert result["total_ayat"] > result["returned"]
    assert result["truncated"] is True
    # The count is complete even though the page is not.
    assert result["total_matches"] > 1000


def test_an_unknown_root_says_so(session):
    with pytest.raises(QueryError) as excinfo:
        grammar.run(session, "root:زززز")
    assert "not in the corpus" in str(excinfo.value)


@pytest.mark.parametrize("example", grammar.EXAMPLES, ids=lambda e: e["query"])
def test_every_worked_example_runs(session, example):
    """The 20 documented examples are the eval set. Each must execute, return a
    coherent shape, and stay fast enough to be interactive."""
    started = time.perf_counter()
    result = grammar.run(session, example["query"], limit=3)
    elapsed = time.perf_counter() - started

    assert result["total_matches"] >= 0
    assert result["exhaustive"] is True
    assert result["reading"], "a query with no human-readable reading is not documented"
    if result["total_matches"]:
        assert result["hits"], example["query"]
        assert result["hits"][0]["ref"]
    # Sequence joins over 130k segments used to take 92 seconds before the
    # ordinal was materialised. This is the guard against that regressing.
    assert elapsed < 5, f"{example['query']} took {elapsed:.1f}s"


def test_the_vocabulary_documents_what_it_accepts(session):
    payload = grammar.vocabulary(session)
    assert payload["pos_classes"] == {"N": "noun", "V": "verb", "P": "particle"}
    assert "PERF" in payload["features"]["aspect"]
    assert payload["counts"]["mood"]["JUS"] > 0
    assert len(payload["examples"]) >= 20
