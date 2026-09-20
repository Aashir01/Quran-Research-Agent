"""Cross-run memory.

The tests are mostly about what memory *refuses* to do: serve a retracted
conclusion, cross a tenant boundary, survive a corpus change, or be mistaken for
a source. A memory store that only remembers is a cache; what makes this usable
for research is that it forgets on the right signals and never claims to be
evidence.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from qra.agents import memory as mem
from qra.agents.ledger import EvidenceLedger
from qra.models import Finding, MemoryEntry, User
from qra.security.auth import Principal


def _principal(session, email: str, org_id: int | None = None) -> Principal:
    from qra.security.service import register_user

    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = register_user(
            session, email=email, password="pw-for-tests-1234", display_name=email.split("@")[0]
        )
        session.commit()
    return Principal(
        user_id=user.id,
        email=user.email,
        role="researcher",
        org_id=org_id,
        display_name=user.display_name,
        issuer="test",
    )


@pytest.fixture(autouse=True)
def _leave_no_trace(session):
    high = session.scalar(select(func.max(MemoryEntry.id))) or 0
    high_finding = session.scalar(select(func.max(Finding.id))) or 0
    mem.invalidate_revision()
    yield
    # A test that left the transaction dirty must not also take the cleanup
    # down with it, or its rows leak into the next test as phantom memories.
    session.rollback()
    session.query(MemoryEntry).filter(MemoryEntry.id > high).delete(synchronize_session=False)
    session.query(Finding).filter(Finding.id > high_finding).delete(synchronize_session=False)
    session.commit()
    mem.invalidate_revision()


def _org(session, slug: str):
    from qra.models import Organisation

    org = session.scalar(select(Organisation).where(Organisation.slug == slug))
    if org is None:
        org = Organisation(slug=slug, name=slug)
        session.add(org)
        session.commit()
    return org


@pytest.fixture
def alice(session):
    """Deliberately inside an organisation rather than org-less.

    An org-less principal shares the personal bucket with every agent run in
    the rest of the suite, and the Librarian now harvests memories from those.
    A test that counts rows in that bucket is really asserting that nothing
    else in the suite ran a research graph. Scoping alice puts her behind the
    tenancy boundary the module already enforces, so the counts are hers.
    """
    return _principal(session, "memory-alice@example.org", org_id=_org(session, "memory-alice-org").id)


@pytest.fixture
def org_user(session):
    return _principal(session, "memory-org@example.org", org_id=_org(session, "memory-test-org").id)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def test_remember_stores_a_result(session, alice):
    row = mem.remember(
        session,
        kind="result",
        key="root:صبر",
        statement="Occurs 103 times, concentrated in Madani surahs.",
        detail={"count": 103},
        principal=alice,
    )
    assert row["kind"] == "result"
    assert row["confirmations"] == 1
    assert row["confirmed_existing"] is False
    assert row["detail"]["count"] == 103


def test_every_memory_says_it_is_not_citable(session, alice):
    row = mem.remember(
        session,
        kind="result",
        key="root:صبر",
        statement="Occurs 103 times, concentrated in Madani surahs.",
        principal=alice,
    )
    # Load-bearing: the planner routes recalled memories into open questions
    # rather than spans precisely because of this flag.
    assert row["citable"] is False
    assert row["source"] == "memory"


def test_relearning_confirms_rather_than_duplicates(session, alice):
    first = mem.remember(
        session,
        kind="dead_end",
        key="analysis:rhyme makki madani",
        statement="Rhyme concentration shows no Makki/Madani difference.",
        run_id="run-a",
        principal=alice,
    )
    second = mem.remember(
        session,
        kind="dead_end",
        key="analysis:rhyme makki madani",
        statement="Rhyme concentration shows no Makki/Madani difference.",
        run_id="run-b",
        principal=alice,
    )
    assert second["id"] == first["id"]
    assert second["confirmations"] == 2
    assert second["confirmed_existing"] is True


def test_the_same_run_repeating_itself_is_not_corroboration(session, alice):
    kw = {
        "kind": "dead_end",
        "key": "analysis:rhyme",
        "statement": "Rhyme concentration shows no Makki/Madani difference.",
        "run_id": "run-a",
        "principal": alice,
    }
    mem.remember(session, **kw)
    again = mem.remember(session, **kw)
    # Two runs agreeing is evidence about the finding. One run saying it twice
    # is evidence about the loop it is in.
    assert again["confirmations"] == 1


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"kind": "guess"}, "unknown memory kind"),
        ({"key": ""}, "needs a key"),
        ({"statement": "short"}, "too short"),
        ({"statement": "x" * 700}, "too long"),
        ({"evidence_level": "L9"}, "unknown evidence level"),
    ],
)
def test_bad_memories_are_refused(session, alice, kwargs, fragment):
    base = {
        "kind": "result",
        "key": "root:صبر",
        "statement": "Occurs 103 times across the corpus.",
        "principal": alice,
    }
    with pytest.raises(mem.MemoryError_) as exc:
        mem.remember(session, **{**base, **kwargs})
    assert fragment in str(exc.value)


def test_a_refused_write_leaves_nothing_behind(session, alice):
    before = session.scalar(select(func.count()).select_from(MemoryEntry))
    with pytest.raises(mem.MemoryError_):
        mem.remember(session, kind="result", key="root:صبر", statement="no", principal=alice)
    # Validation happens before any row is constructed, so a caught error cannot
    # leave a half-written memory for the next commit to persist.
    assert session.scalar(select(func.count()).select_from(MemoryEntry)) == before


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


def test_recall_finds_by_key(session, alice):
    mem.remember(
        session,
        kind="result",
        key="root:صبر",
        statement="Occurs 103 times across the corpus.",
        principal=alice,
    )
    rows = mem.recall(session, ["root:صبر"], principal=alice)
    assert len(rows) == 1
    assert rows[0]["key"] == "root:صبر"


def test_recall_orders_by_corroboration(session, alice):
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="Seen once and never checked again.", run_id="r1", principal=alice,
    )
    for run in ("r1", "r2", "r3"):
        mem.remember(
            session, kind="result", key="root:صبر",
            statement="Reached independently by three separate runs.",
            run_id=run, principal=alice,
        )
    rows = mem.recall(session, ["root:صبر"], principal=alice)
    assert rows[0]["confirmations"] == 3


def test_recall_is_scoped_to_the_tenant(session, alice, org_user):
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="An organisation's private conclusion about sabr.",
        principal=org_user,
    )
    # Another team's memory is a leak, not a feature — the same rule the
    # prior-work search follows.
    assert mem.recall(session, ["root:صبر"], principal=alice) == []
    assert len(mem.recall(session, ["root:صبر"], principal=org_user)) == 1


def test_recall_filters_by_kind(session, alice):
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="A positive result about sabr.", principal=alice,
    )
    mem.remember(
        session, kind="dead_end", key="root:صبر",
        statement="A null result about sabr and rhyme.", principal=alice,
    )
    rows = mem.recall(session, ["root:صبر"], kinds=("dead_end",), principal=alice)
    assert [r["kind"] for r in rows] == ["dead_end"]


def test_unknown_kind_in_a_filter_is_refused(session, alice):
    with pytest.raises(mem.MemoryError_):
        mem.recall(session, ["root:صبر"], kinds=("vibes",), principal=alice)


def test_recall_with_no_keys_returns_nothing(session, alice):
    # A key that matches everything recalls everything, which is the same as
    # recalling nothing — so an empty key list must not fall back to "all".
    assert mem.recall(session, [], principal=alice) == []
    assert mem.recall(session, ["", "  "], principal=alice) == []


# ---------------------------------------------------------------------------
# forgetting
# ---------------------------------------------------------------------------


def test_forget_marks_stale_without_deleting(session, alice):
    row = mem.remember(
        session, kind="result", key="root:صبر",
        statement="A conclusion later found to be wrong.", principal=alice,
    )
    mem.forget(session, row["id"], reason="the control was not length-matched", principal=alice)
    assert mem.recall(session, ["root:صبر"], principal=alice) == []
    # The row survives: "we used to believe this, and here is why we stopped"
    # is itself worth keeping.
    kept = mem.recall(session, ["root:صبر"], principal=alice, include_stale=True)
    assert len(kept) == 1
    assert "length-matched" in kept[0]["stale_reason"]


def test_forgetting_requires_a_reason(session, alice):
    row = mem.remember(
        session, kind="result", key="root:صبر",
        statement="A conclusion later found to be wrong.", principal=alice,
    )
    with pytest.raises(mem.MemoryError_):
        mem.forget(session, row["id"], reason="", principal=alice)
    assert session.get(MemoryEntry, row["id"]).stale_reason is None


def test_cannot_forget_another_tenants_memory(session, alice, org_user):
    row = mem.remember(
        session, kind="result", key="root:صبر",
        statement="An organisation's private conclusion about sabr.",
        principal=org_user,
    )
    with pytest.raises(mem.MemoryError_):
        mem.forget(session, row["id"], reason="not mine to forget", principal=alice)
    assert session.get(MemoryEntry, row["id"]).stale_reason is None


def test_retracting_a_finding_invalidates_its_memories(session, alice):
    finding = Finding(
        author_id=alice.user_id, question="q", summary="s", fingerprint="fp-memory-test"
    )
    session.add(finding)
    session.commit()
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="A conclusion resting on a finding that gets retracted.",
        finding_id=finding.id, principal=alice,
    )
    count = mem.invalidate_for_finding(session, finding.id, reason="retracted on review")
    assert count == 1
    # Otherwise a rejected conclusion is laundered back into the next run by a
    # planner that never saw the rejection.
    assert mem.recall(session, ["root:صبر"], principal=alice) == []


# ---------------------------------------------------------------------------
# corpus revision
# ---------------------------------------------------------------------------


def test_a_memory_from_another_corpus_build_is_withheld(session, alice):
    row = mem.remember(
        session, kind="result", key="root:صبر",
        statement="Occurs 103 times, counted against an earlier corpus.",
        principal=alice,
    )
    stored = session.get(MemoryEntry, row["id"])
    stored.corpus_revision = "a-different-build"
    session.commit()
    # A count from a corpus that has since changed is not wrong, it is
    # unverified — so it is withheld rather than served or deleted.
    assert mem.recall(session, ["root:صبر"], principal=alice) == []
    assert mem.stats(session, principal=alice)["outdated"] == 1


def test_relearning_under_the_current_corpus_revives_a_stale_memory(session, alice):
    row = mem.remember(
        session, kind="result", key="root:صبر",
        statement="Occurs 103 times across the corpus.", run_id="r1", principal=alice,
    )
    stored = session.get(MemoryEntry, row["id"])
    stored.corpus_revision = "a-different-build"
    stored.stale_reason = "the corpus changed under it"
    session.commit()
    again = mem.remember(
        session, kind="result", key="root:صبر",
        statement="Occurs 103 times across the corpus.", run_id="r2", principal=alice,
    )
    assert again["stale_reason"] is None
    assert len(mem.recall(session, ["root:صبر"], principal=alice)) == 1


def test_a_reason_to_forget_survives_relearning(session, alice):
    row = mem.remember(
        session, kind="result", key="root:صبر",
        statement="Occurs 103 times across the corpus.", run_id="r1", principal=alice,
    )
    mem.forget(session, row["id"], reason="the control was not length-matched", principal=alice)
    again = mem.remember(
        session, kind="result", key="root:صبر",
        statement="Occurs 103 times across the corpus.", run_id="r2", principal=alice,
    )
    # Relearning under the *same* corpus clears nothing: a human judged this
    # wrong, and re-deriving it does not overrule them.
    assert again["stale_reason"] is not None
    assert mem.recall(session, ["root:صبر"], principal=alice) == []


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------


def test_keys_come_from_resolved_terms_before_raw_words(session):
    keys = mem.keys_for(
        "does sabr accompany salah?",
        [{"kind": "concept", "value": "patience", "roots": ["صبر"]}],
    )
    assert keys[0] == "concept:patience"
    assert "root:صبر" in keys
    assert "term:sabr" in keys


def test_short_words_are_not_keys(session):
    # "the", "and", "is" would match across the whole corpus of memories.
    assert mem.keys_for("is it the one?") == []


# ---------------------------------------------------------------------------
# harvesting
# ---------------------------------------------------------------------------


def _ledger_with(label: str, payload: dict) -> EvidenceLedger:
    ledger = EvidenceLedger("does sabr accompany salah?", run_id="harvest-run")
    ledger.add_statistic(label, payload)
    return ledger


# The payloads below come from the tools themselves rather than being written
# by hand. An earlier version of these tests invented a flat {"p_value": ...}
# shape and passed against it, while the real statistics nest their verdict
# under "significance" — so harvest would have taken nothing from an actual run
# and the tests would have said it worked.


def test_harvest_reads_a_real_distribution_payload(session, alice):
    from qra import tools

    dist = tools.root_distribution(session, "صبر")
    ledger = _ledger_with("distribution:صبر", dist["makki_madani"])
    out = mem.harvest(session, ledger, principal=alice)

    assert len(out) == 1
    assert out[0]["key"] == "root:صبر"
    # سبر's Makki/Madani split is within chance (p≈0.13), so this is a dead end
    # and recording it is the point: the next run does not redo it.
    assert out[0]["kind"] == "dead_end"
    assert out[0]["detail"]["significance"]["within_chance"] is True


def test_harvest_reads_a_real_cooccurrence_payload(session, alice):
    from qra import tools

    assoc = tools.cooccurrence(session, "صبر", "صلو")
    ledger = _ledger_with("cooccurrence:صبر+صلو", assoc)
    out = mem.harvest(session, ledger, principal=alice)

    assert out[0]["kind"] == "result"
    assert out[0]["key"] == "pair:صبر+صلو"


def test_a_pair_key_does_not_depend_on_the_order_asked(session, alice):
    from qra import tools

    assoc = tools.cooccurrence(session, "صبر", "صلو")
    first = mem.harvest(session, _ledger_with("cooccurrence:صبر+صلو", assoc), principal=alice)
    # The same question asked the other way round must reach the same memory,
    # or each run hides its result from the other.
    reversed_ = tools.cooccurrence(session, "صلو", "صبر")
    second = mem.harvest(
        session,
        _ledger_with("cooccurrence:صلو+صبر", reversed_),
        principal=alice,
    )
    assert first[0]["key"] == second[0]["key"] == "pair:صبر+صلو"


def test_within_chance_beats_a_raw_p_value(session, alice):
    # The tools state their verdict directly, having already applied whatever
    # correction they judged necessary. A raw p below alpha does not override a
    # tool that has said the result is within chance.
    ledger = _ledger_with(
        "distribution:صبر",
        {"significance": {"p_value": 0.001, "within_chance": True}},
    )
    assert mem.harvest(session, ledger, principal=alice)[0]["kind"] == "dead_end"


def test_a_corrected_p_is_preferred_over_the_raw_one(session, alice):
    ledger = _ledger_with(
        "distribution:صبر",
        {"significance": {"p_value": 0.01, "corrected_p": 0.40, "correction": "bh"}},
    )
    out = mem.harvest(session, ledger, principal=alice)
    # Comparing the raw p against alpha after a correction was applied reports
    # an effect the analysis itself had already discounted.
    assert out[0]["kind"] == "dead_end"
    assert "corrected p=0.4" in out[0]["statement"]


def test_a_statistic_with_no_significance_block_is_not_harvested(session, alice):
    ledger = _ledger_with("conditionals", {"matched": 12, "corpus_total": 1500})
    # No verdict means unmeasured, not null. Recording it either way would put
    # a claim in memory that the run never made.
    assert mem.harvest(session, ledger, principal=alice) == []


def test_a_nazm_statistic_keys_to_its_surah(session, alice):
    ledger = _ledger_with(
        "nazm:surah:12", {"passages": 8, "significance": {"within_chance": False}}
    )
    assert mem.harvest(session, ledger, principal=alice)[0]["key"] == "surah:12"


def test_harvest_takes_refuted_claims_and_leaves_supported_ones(session, alice):
    ledger = EvidenceLedger("does sabr accompany salah?", run_id="harvest-claims")
    refuted = ledger.add_claim("Sabr appears only in Madani surahs", author="planner")
    ledger.add_claim("Sabr appears across both periods", author="planner", status="confirmed")
    ledger.set_claim_status(refuted, "refuted")
    out = mem.harvest(session, ledger, principal=alice)
    kinds = {row["kind"] for row in out}
    assert kinds == {"dead_end"}
    # A supported claim belongs in the finding, where its evidence sits beside
    # it. Lifting it into memory produces the free-floating assertion this
    # module exists to prevent.
    assert all("appears across both periods" not in row["statement"] for row in out)


def test_harvested_memories_carry_the_run_and_finding(session, alice):
    finding = Finding(
        author_id=alice.user_id, question="q", summary="s", fingerprint="fp-memory-harvest"
    )
    session.add(finding)
    session.commit()
    from qra import tools

    ledger = _ledger_with("cooccurrence:صبر+صلو", tools.cooccurrence(session, "صبر", "صلو"))
    out = mem.harvest(session, ledger, finding_id=finding.id, principal=alice)
    assert out[0]["finding_id"] == finding.id
    assert out[0]["run_id"] == "harvest-run"


def test_stats_counts_what_is_usable(session, alice):
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="A live conclusion about sabr.", principal=alice,
    )
    row = mem.remember(
        session, kind="dead_end", key="root:صلو",
        statement="A conclusion that was later retracted.", principal=alice,
    )
    mem.forget(session, row["id"], reason="superseded by a better control", principal=alice)
    out = mem.stats(session, principal=alice)
    assert out["total"] == 2
    assert out["stale"] == 1
    assert out["by_kind"] == {"result": 1, "dead_end": 1}


# ---------------------------------------------------------------------------
# the run loop
# ---------------------------------------------------------------------------


def test_the_planner_surfaces_memory_as_an_open_question(session, alice):
    from qra.agents.roles import AgentContext, Planner

    mem.remember(
        session,
        kind="dead_end",
        key="term:sabr",
        statement="Rhyme concentration shows no Makki/Madani difference.",
        principal=alice,
    )
    ledger = EvidenceLedger("what is known about sabr?", run_id="planner-recall")
    ctx = AgentContext(session=session, ledger=ledger, principal=alice)
    recalled = Planner()._recall(ctx, [])

    assert len(recalled) == 1
    text = "\n".join(ledger.open_questions)
    assert "Earlier run found nothing here" in text
    assert "memory, not evidence" in text
    # Only spans become citations. A memory that reached them would be cited as
    # a source for the conclusion it is a memory of.
    assert ledger.spans == {}
    assert ledger.cited_refs() == set()


def test_the_planner_survives_memory_being_unavailable(session, alice, monkeypatch):
    from qra.agents.roles import AgentContext, Planner

    def boom(*args, **kwargs):
        raise RuntimeError("memory table is gone")

    monkeypatch.setattr(mem, "recall", boom)
    ledger = EvidenceLedger("what is known about sabr?", run_id="planner-degraded")
    ctx = AgentContext(session=session, ledger=ledger, principal=alice)
    # Memory is an optimisation. A run that cannot recall is a slower run, not
    # a failed one.
    assert Planner()._recall(ctx, []) == []
    assert any(e.action == "memory_unavailable" for e in ledger.events)


def test_a_reviewer_rejecting_a_finding_invalidates_its_memories(session, alice):
    from qra.models import User
    from qra.security.auth import Principal
    from qra.workspace import service

    reviewer_row = session.scalar(select(User).where(User.email == "memory-reviewer@example.org"))
    if reviewer_row is None:
        from qra.security.service import register_user

        reviewer_row = register_user(
            session, email="memory-reviewer@example.org", password="pw-for-tests-1234"
        )
        session.commit()
    reviewer = Principal(
        user_id=reviewer_row.id, email=reviewer_row.email, role="reviewer",
        org_id=None, display_name="r", issuer="test",
    )

    finding = Finding(
        author_id=alice.user_id, question="q", summary="s", fingerprint="fp-memory-review"
    )
    session.add(finding)
    session.commit()
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="A conclusion the reviewers send back for more work.",
        finding_id=finding.id, principal=alice,
    )

    out = service.review_finding(
        session, finding.id, reviewer_id=reviewer.user_id, approve=False, principal=reviewer
    )
    assert out["memories_invalidated"] == 1
    assert mem.recall(session, ["root:صبر"], principal=alice) == []


def test_approving_a_finding_leaves_its_memories_alone(session, alice):
    from qra.models import User
    from qra.security.auth import Principal
    from qra.workspace import service

    reviewer_row = session.scalar(select(User).where(User.email == "memory-reviewer@example.org"))
    if reviewer_row is None:
        from qra.security.service import register_user

        reviewer_row = register_user(
            session, email="memory-reviewer@example.org", password="pw-for-tests-1234"
        )
        session.commit()
    reviewer = Principal(
        user_id=reviewer_row.id, email=reviewer_row.email, role="reviewer",
        org_id=None, display_name="r", issuer="test",
    )
    finding = Finding(
        author_id=alice.user_id, question="q", summary="s", fingerprint="fp-memory-approve"
    )
    session.add(finding)
    session.commit()
    mem.remember(
        session, kind="result", key="root:صبر",
        statement="A conclusion that survives review intact.",
        finding_id=finding.id, principal=alice,
    )
    out = service.review_finding(
        session, finding.id, reviewer_id=reviewer.user_id, approve=True, principal=reviewer
    )
    assert out["memories_invalidated"] == 0
    assert len(mem.recall(session, ["root:صبر"], principal=alice)) == 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from qra.api.main import app

    return TestClient(app)


def test_api_round_trip(client, session):
    created = client.post(
        "/memory",
        json={
            "kind": "dead_end",
            "key": "analysis:api probe",
            "statement": "Tested through the API and found nothing there.",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["citable"] is False

    found = client.get("/memory", params={"key": ["analysis:api probe"]})
    assert found.status_code == 200
    payload = found.json()
    assert payload["count"] == 1
    assert "not a source" in payload["note"]

    forgotten = client.post(
        f"/memory/{body['id']}/forget", json={"reason": "the probe was not a real analysis"}
    )
    assert forgotten.status_code == 200
    assert client.get("/memory", params={"key": ["analysis:api probe"]}).json()["count"] == 0


def test_api_refuses_a_bad_memory(client):
    bad = client.post(
        "/memory", json={"kind": "vibes", "key": "analysis:x", "statement": "long enough to pass"}
    )
    assert bad.status_code == 422
    assert "unknown memory kind" in bad.json()["detail"]


def test_two_resolved_roots_produce_the_pair_key_harvest_writes(session):
    keys = mem.keys_for(
        "does sabr accompany salah?",
        [
            {"kind": "concept", "value": "patience", "roots": ["صبر"]},
            {"kind": "concept", "value": "prayer", "roots": ["صلو"]},
        ],
    )
    # Harvest keys a co-occurrence result to "pair:a+b". Without the matching
    # key here, the result from the last run to ask this stays invisible to the
    # next one — the exact repetition memory exists to stop.
    assert "pair:صبر+صلو" in keys
