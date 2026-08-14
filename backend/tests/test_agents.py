"""Agent behaviour that must hold with no model configured."""

from qra.agents.graph import ResearchGraph
from qra.agents.ledger import EvidenceLedger
from qra.agents.render import render
from qra.agents.roles import AGENTS, AgentContext, CriticAgent
from qra.retrieval.deterministic import get_ayah


def test_render_pulls_scripture_from_the_database(session):
    out = render(session, "The verse: {{ayah:2:255}}", strict=True)
    ayah = get_ayah(session, 2, 255)
    assert ayah.text in out.text
    assert out.placeholders_resolved == 1
    assert out.violations == []
    assert out.citations[0]["ref"] == "2:255"


def test_nonexistent_reference_is_a_visible_failure(session):
    out = render(session, "{{ayah:2:999}}", strict=True)
    assert out.violations
    assert "does not exist" in out.violations[0]
    assert "UNRESOLVED" in out.text  # never silently plausible text


def test_translation_placeholder_names_its_edition(session):
    out = render(session, "{{translation:2:255|ur-jalandhry}}", strict=True)
    assert out.placeholders_resolved == 1
    assert out.citations[0]["edition_slug"] == "ur-jalandhry"


def test_hadith_placeholder_carries_the_grading(session):
    out = render(session, "{{hadith:hadith-bukhari|1}}", strict=True)
    assert "grading" in out.text
    assert out.citations[0]["grading"]


def test_critic_rejects_a_fabricated_citation(session):
    ledger = EvidenceLedger("test")
    ctx = AgentContext(session=session, ledger=ledger)
    from qra.agents.ledger import LedgerSpan

    ledger.spans["fake"] = LedgerSpan(
        id="fake",
        kind="ayah",
        text="…",
        citation={"kind": "ayah", "ref": "2:999"},
        ref="2:999",
        ayah_id=None,
        retrieval_mode="deterministic",
        retrieved_by="test",
        query="test",
    )
    report = CriticAgent().run(ctx)
    assert report["citations_failed"]
    assert report["verdict"] == "blocked"


def test_critic_downgrades_unsupported_claims(session):
    ledger = EvidenceLedger("test")
    ctx = AgentContext(session=session, ledger=ledger)
    claim_id = ledger.add_claim("An assertion with no evidence behind it.")
    CriticAgent().run(ctx)
    assert ledger.claims[claim_id].status == "needs_evidence"


def test_critic_falsifies_a_universal_question(session):
    ledger = EvidenceLedger("Does sabr always come with salah?", language="en")
    ctx = AgentContext(session=session, ledger=ledger)
    report = CriticAgent().run(ctx)
    tested = report["universal_claims_tested"]
    assert tested and tested[0]["verdict"] == "refuted"
    assert tested[0]["violating_count"] > 0


def test_full_run_without_a_model_still_produces_verified_output(session):
    graph = ResearchGraph(session)
    ledger = graph.run("Does sabr always come with salah?", language="en")
    assert ledger.draft
    assert ledger.spans
    assert ledger.critic_report is not None
    # No scripture was typed by any agent.
    assert ledger.critic_report["scripture_violations"] == []
    assert ledger.critic_report["citations_failed"] == []
    rendered = render(session, ledger.draft, strict=False)
    assert rendered.placeholders_resolved > 0


def test_ledger_round_trips_through_json(session):
    ledger = EvidenceLedger("q", language="ur")
    ledger.add_plan(["step"], ["sub?"])
    ledger.add_claim("a claim", status="confirmed")
    restored = EvidenceLedger.from_dict(ledger.to_dict())
    assert restored.question == "q"
    assert restored.claims["c1"].status == "confirmed"
    assert restored.sub_questions["q1"].text == "sub?"


def test_every_agent_is_registered():
    expected = {
        "planner", "corpus", "lisan", "tafsir", "hadith",
        "pattern", "nazm", "critic", "scribe", "librarian",
    }
    assert expected <= set(AGENTS)
