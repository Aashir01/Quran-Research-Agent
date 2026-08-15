"""Tracing must never be the reason something fails, and must work unconfigured."""

import pytest

from qra.observability import RECORDER, status, trace


def test_spans_are_recorded_with_durations():
    with trace("demo", kind="tool", run_id="test-run", root="صبر") as span:
        span["result"] = {"total_occurrences": 103}
    spans = RECORDER.spans("test-run")
    assert spans and spans[-1]["name"] == "demo"
    assert spans[-1]["duration_ms"] >= 0
    assert spans[-1]["output"]["total_occurrences"] == 103


def test_failures_are_recorded_and_re_raised():
    with pytest.raises(ValueError):
        with trace("boom", run_id="test-fail"):
            raise ValueError("nope")
    span = RECORDER.spans("test-fail")[-1]
    assert "ValueError" in span["error"]


def test_corpus_text_is_not_shipped_in_span_payloads():
    """Spans carry shape and counts, not scripture — a licence question we skip."""
    long_text = "ٱلۡحَمۡدُ لِلَّهِ رَبِّ ٱلۡعَٰلَمِينَ " * 20
    with trace("render", run_id="test-privacy", text=long_text) as span:
        span["result"] = {"hits": [{"text": long_text}] * 5}
    recorded = RECORDER.spans("test-privacy")[-1]
    assert recorded["output"] == {"hits_count": 5}
    assert len(recorded["input"]["text"]) <= 120


def test_status_reports_local_recorder_when_langfuse_is_unconfigured():
    payload = status()
    assert payload["local_recorder"]["enabled"] is True
    assert payload["langfuse"]["enabled"] is False
    assert "not set" in payload["langfuse"]["reason"]


def test_agent_run_is_traced_under_the_ledger_run_id(session):
    from qra.agents.graph import ResearchGraph

    ledger = ResearchGraph(session).run("Does sabr always come with salah?", language="en")
    spans = RECORDER.spans(ledger.run_id)
    names = [s["name"] for s in spans]
    assert "planner" in names and "critic" in names and "scribe" in names
    assert all(s["kind"] == "agent" for s in spans)
