"""Scope estimation and critic escalation (Track E).

The most useful thing a research tool can say before a long run is what kind of
question it has been given. The commonest disappointment with a corpus tool is
asking an interpretive question and receiving counts — and that is knowable in
advance, from the wording, without running anything.
"""

from __future__ import annotations

import pytest

from qra.agents.escalation import escalate, should_escalate
from qra.agents.scope import estimate

# --- question shape ---------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "shape"),
    [
        ("How many times does the root صبر occur?", "decidable"),
        ("Does patience always appear with prayer?", "decidable"),
        ("Compare knowledge in Makki versus Madani surahs", "comparative"),
        ("Why does the Quran mention the heart so often?", "interpretive"),
        ("What is the meaning of sabr?", "interpretive"),
    ],
)
def test_the_shape_of_a_question_is_named_before_it_is_run(session, question, shape):
    assert estimate(session, question)["shape"] == shape


def test_a_universal_claim_outranks_a_count(session):
    """'How many verses say X always happens' is a universal claim first and a
    counting question second — the order the markers are tested in matters."""
    result = estimate(session, "How many verses show that patience always brings relief?")
    assert result["shape"] == "decidable"
    assert "counter-example" in result["shape_note"]


def test_an_interpretive_question_is_told_retrieval_cannot_close_it(session):
    result = estimate(session, "Why does the Quran mention the heart so often?")
    assert any("cannot close an interpretive question" in w for w in result["warnings"])
    assert "judgement" in result["shape_note"]


def test_concept_labels_with_alternatives_still_match(session):
    """Several labels carry alternatives — 'Patience / steadfastness' — and
    requiring the whole string meant a question saying 'patience' matched
    nothing at all."""
    labels = {t["label"] for t in estimate(session, "does patience matter?")["terms"]}
    assert any(label.startswith("Patience") for label in labels)


def test_an_unrecognised_question_is_warned_about_rather_than_guessed_at(session):
    result = estimate(session, "Tell me about zzzz")
    assert result["terms_found"] == 0
    assert result["evidence_base"].startswith("none")
    assert any("was recognised" in w for w in result["warnings"])


def test_a_counting_question_needs_no_provider(session):
    """Providers draft; they never retrieve. A question that only counts is
    answerable with every provider unreachable."""
    result = estimate(session, "How many times does the root صبر occur?")
    assert result["needs_a_model_provider"] is False
    assert "never retrieve" in result["provider_note"]


def test_the_estimate_runs_nothing(session):
    """An estimate that costs as much as the answer is not an estimate."""
    import time

    start = time.perf_counter()
    result = estimate(session, "Compare knowledge in Makki versus Madani surahs")
    assert time.perf_counter() - start < 2.0
    assert "not an estimate" in result["estimate_only"]


def test_a_thin_evidence_base_is_flagged(session):
    """Enough to describe, not enough to establish — and the Critic will refuse
    a comparative claim built on it, so saying so first saves the run."""
    result = estimate(session, "what about برزخ")
    if result["widest_term_reaches_ayat"] and result["widest_term_reaches_ayat"] < 10:
        assert any("enough to describe" in w for w in result["warnings"])


# --- escalation -------------------------------------------------------------


def test_a_clean_critic_report_does_not_escalate():
    warranted, reasons = should_escalate(
        {"citations_failed": [], "claims_without_support": [], "numerology_notes": []}
    )
    assert warranted is False
    assert reasons == []


def test_each_trigger_warrants_a_second_look():
    for key in (
        "scripture_violations",
        "claims_from_flagged_spans",
        "claims_without_support",
        "numerology_notes",
        "citations_failed",
    ):
        warranted, reasons = should_escalate({key: ["something"]})
        assert warranted, key
        assert reasons


def test_escalation_runs_with_no_providers(session):
    """The second pass is independent by *mechanism*, not by model. If it needed
    a provider it would be unavailable exactly when the first pass was too."""
    result = escalate(
        session,
        critic_report={"claims_without_support": ["x"]},
        claim="nazala always means physical descent",
        roots=["نزل"],
    )
    assert result["second_pass"]["objections"]
    assert "every provider unreachable" in result["second_pass"]["independence"]


def test_a_disagreement_is_reported_rather_than_merged(session):
    """Collapsing a disagreement into one verdict throws away the only signal an
    escalation produces."""
    result = escalate(
        session, critic_report={"claims_without_support": ["x"]}, claim="a plain statement"
    )
    assert result["first_pass"]["flagged"] is True
    assert result["second_pass"]["flagged"] is False
    assert "disagree" in result["reading"]


def test_agreement_is_not_overclaimed(session):
    """Two checks agreeing is weak evidence — they can share a blind spot."""
    result = escalate(
        session,
        critic_report={"numerology_notes": ["19"]},
        claim="nazala always means descent",
        roots=["نزل"],
    )
    assert result["agreement"] == "both passes flagged this draft"
    assert "weak evidence" in result["reading"]


def test_the_absence_of_a_second_provider_is_stated_not_hidden(session):
    """Reporting a single-provider review as adversarial would be worse than
    not running one."""
    result = escalate(session, critic_report={"claims_without_support": ["x"]}, claim="x")
    model_pass = result["adversarial_model_pass"]
    assert isinstance(model_pass["available"], bool)
    assert model_pass["note"]
    if not model_pass["available"]:
        assert "would be worse than not running one" in model_pass["policy"]
