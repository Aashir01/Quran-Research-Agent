"""Track D analysis engines.

Each of these four engines was designed around a specific way it could be
misused, so the tests are mostly about what the engines *refuse* and what order
they say things in — not about whether the arithmetic runs.

* The sandbox must state the denominator before any result (WP-33).
* Cross-corpus transfer must be able to say "that's just Arabic" (WP-34).
* Iltifat must compare words, not segments, or an Arabic object suffix reads as
  a shift of voice (WP-27).
* Naskh must refuse a claim with no claimant, because there is no such fact as
  an abrogated verse on nobody's authority (WP-30).
"""

from __future__ import annotations

import pytest

from qra.analytics import balagha, naskh, sandbox, transfer
from qra.analytics.naskh import NaskhError
from qra.analytics.sandbox import SandboxError

# --- WP-33: the numerical sandbox -----------------------------------------


@pytest.fixture(autouse=True)
def _leave_no_trace(session):
    """Remove the rows a test wrote.

    Not tidiness. ``naskh.registry`` reports that it ships empty, and a test
    claim left behind would make that statement false in the running app — the
    registry's emptiness is a design position, not an accident of seeding.
    """
    from sqlalchemy import func, select

    from qra.models import NaskhClaim, SandboxSession, SandboxTest

    high = {
        model: session.scalar(select(func.max(model.id))) or 0
        for model in (SandboxSession, SandboxTest, NaskhClaim)
    }
    yield
    for model, ceiling in high.items():
        session.query(model).filter(model.id > ceiling).delete(synchronize_session=False)
    session.commit()




@pytest.fixture
def sandbox_session(session):
    return sandbox.open_session(
        session,
        owner_id=None,
        title="muqatta'at letter frequencies",
        intent="whether letter counts in the opening letters differ from the surah body",
    )


def test_a_session_must_state_its_intent_before_looking(session):
    """A session with no stated intent cannot be told apart later from a fishing
    expedition, which is the whole distinction the sandbox is drawing."""
    with pytest.raises(SandboxError, match="before you start looking"):
        sandbox.open_session(session, owner_id=None, title="letters", intent="   ")


def test_a_test_must_name_its_null_model(session, sandbox_session):
    with pytest.raises(SandboxError, match="null model"):
        sandbox.register(
            session,
            sandbox_session["id"],
            claim="alif appears more often than chance in al-Baqarah",
            null_model="",
        )


def test_registration_does_not_count_anything(session, sandbox_session):
    """Pre-registration is the point: the claim is fixed before the number."""
    test = sandbox.register(
        session,
        sandbox_session["id"],
        claim="alif is over-represented in al-Baqarah",
        null_model="corpus-wide alif rate per letter",
    )
    assert test["ran"] is False
    assert test["observed"] is None
    assert test["verdict"] is None


def test_a_test_cannot_be_run_twice(session, sandbox_session):
    """Re-running until it comes out significant is the failure being prevented."""
    test = sandbox.register(
        session,
        sandbox_session["id"],
        claim="lam is over-represented",
        null_model="corpus-wide lam rate",
    )
    sandbox.run(session, test["id"], observed=120, n=1000, baseline_rate=0.1)
    with pytest.raises(SandboxError, match="already run"):
        sandbox.run(session, test["id"], observed=200, n=1000, baseline_rate=0.1)


def test_the_headline_states_the_denominator_before_any_result(session, sandbox_session):
    """The acceptance criterion for WP-33, verbatim: how many hypotheses were
    tried and how many significant results chance predicts, stated *first*."""
    for index in range(40):
        test = sandbox.register(
            session,
            sandbox_session["id"],
            claim=f"letter {index} is over-represented",
            null_model="corpus-wide rate for that letter",
        )
        sandbox.run(session, test["id"], observed=105, n=1000, baseline_rate=0.1)

    summary = sandbox.summary(session, sandbox_session["id"])
    assert summary["headline"] == (
        "You tested 40 hypotheses; 2.0 significant results are expected by chance alone."
    )
    # Ordering is part of the product rule, not a presentation detail.
    keys = list(summary)
    assert keys.index("headline") < keys.index("tests")
    assert summary["expected_by_chance"] == 2.0


def test_a_result_never_leaves_without_the_family_correction(session, sandbox_session):
    """A p-value from this module always arrives with the session it belongs to."""
    test = sandbox.register(
        session,
        sandbox_session["id"],
        claim="mim is over-represented",
        null_model="corpus-wide mim rate",
    )
    payload = sandbox.run(session, test["id"], observed=140, n=1000, baseline_rate=0.1)
    assert payload["test"]["corrected_p"] is not None
    assert payload["session"]["correction"].startswith("benjamini_hochberg")
    assert "reviewer sign-off" in payload["watermark"]


def test_the_forty_first_test_changes_the_verdict_on_the_first(session):
    """Correction is over the family, so a later test can pull an earlier one back
    inside chance. Storing an uncorrected p as final would hide exactly that."""
    opened = sandbox.open_session(
        session,
        owner_id=None,
        title="family correction",
        intent="whether adding tests changes earlier verdicts",
    )
    first = sandbox.register(
        session, opened["id"], claim="the striking one", null_model="uniform"
    )
    payload = sandbox.run(session, first["id"], observed=135, n=1000, baseline_rate=0.1)
    alone = payload["test"]["corrected_p"]

    for index in range(30):
        noise = sandbox.register(
            session, opened["id"], claim=f"filler {index}", null_model="uniform"
        )
        sandbox.run(session, noise["id"], observed=101, n=1000, baseline_rate=0.1)

    after = next(
        t
        for t in sandbox.summary(session, opened["id"])["tests"]
        if t["id"] == first["id"]
    )
    assert after["corrected_p"] > alone


def test_a_closed_session_takes_no_more_tests(session, sandbox_session):
    sandbox.close(session, sandbox_session["id"])
    with pytest.raises(SandboxError, match="closed"):
        sandbox.register(
            session, sandbox_session["id"], claim="one more", null_model="uniform"
        )


# --- WP-34: cross-corpus transfer -----------------------------------------


def test_transfer_names_the_background_corpus_and_how_it_matched(session):
    result = transfer.compare_pair(session, "صبر", "صلو")
    assert result["background"]["corpus"] == "hadith"
    assert "surface" in result["background"]["matching"]
    assert result["verdict"] in {
        "general_arabic",
        "distinctive",
        "absent_in_quran",
        "no_background",
        "within_chance_in_both",
    }


def test_transfer_can_say_a_quranic_pattern_is_just_arabic(session):
    """The verdict that justifies the whole work package. If the vocabulary
    cannot express 'this is a property of the language', the check is theatre."""
    verdicts = {
        transfer.compare_pair(session, a, b)["verdict"]
        for a, b in (("صبر", "صلو"), ("علم", "كتب"), ("امن", "عمل"), ("قول", "ربب"))
    }
    assert "general_arabic" in verdicts


def test_transfer_refuses_a_root_it_does_not_have(session):
    assert "not in the corpus" in transfer.compare_pair(session, "صبر", "zzzz")["error"]


def test_a_root_comparison_warns_that_the_rates_are_not_comparable(session):
    result = transfer.compare_root(session, "صبر")
    assert result["quran"]["occurrences"] > 0
    assert "not directly comparable" in result["note"]


# --- WP-27: balagha --------------------------------------------------------


def test_iltifat_compares_words_not_segments(session):
    """2:3 is the textbook case, and the one a naive detector gets wrong.

    ``رَزَقْنَٰهُمْ`` is verb + 1st-person subject + 3rd-person object suffix. A
    segment-level scan reads that suffix as a shift; it is not one, it is who
    the verb acts upon. The ayah has exactly two shifts, both between words.
    """
    result = balagha.iltifat(session, surah=2, limit=200)
    shifts = [c for c in result["candidates"] if c["ref"] == "2:3"]
    assert [(c["from_person"], c["to_person"]) for c in shifts] == [("3", "1"), ("1", "3")]


def test_every_shift_is_labelled_a_suggestion(session):
    """A person shift is a fact about the morphology. Calling it iltifat is a
    reading, and the payload must never blur the two."""
    result = balagha.iltifat(session, surah=2, limit=20)
    assert all(c["provenance"] == "system_suggested" for c in result["candidates"])
    assert "coreference" in result["caveat"]


def test_iltifat_states_how_ordinary_a_shift_is(session):
    """Most ayat contain one, so a bare count is close to no information — the
    baseline has to travel with it."""
    hotspots = balagha.hotspots(session)
    assert 0.4 < hotspots["baseline_rate"] < 0.7
    assert "%" in hotspots["baseline_note"]
    assert hotspots["correction"].startswith("benjamini_hochberg")
    assert hotspots["beyond_chance"] < hotspots["surahs_tested"]


def test_the_hand_verified_fixtures_all_hold(session):
    """WP-27's acceptance. The negatives carry the weight: each is an ayah a
    segment-level detector flags and a correct one does not."""
    report = balagha.check_fixtures(session)
    failed = [f for f in report["fixtures"] if not f["passed"]]
    assert not failed, failed
    assert report["passed"] == report["total"] >= 5
    assert any(f["kind"] == "negative" for f in report["fixtures"])


def test_the_negative_fixture_is_one_a_naive_detector_fails(session):
    """76:2 — "We created him ... We test him ... We made him". First person
    throughout; every attached ه is an object, not a change of voice."""
    result = balagha.iltifat(session, surah=76, limit=200)
    assert not [c for c in result["candidates"] if c["ref"] == "76:2"]


def test_the_module_admits_the_shift_it_cannot_see(session):
    """The most-cited iltifat in the Qur'an is 1:4 → 1:5, which crosses an ayah
    boundary. Scoping within an ayah is right, and the cost has to be stated."""
    result = balagha.iltifat(session, surah=1, limit=50)
    assert "1:4" in result["known_limitation"]
    assert not [c for c in result["candidates"] if c["ref"] == "1:4"]


def test_balagha_says_what_it_will_not_detect(session):
    """The honest half of a rhetoric module is the list of things it declines."""
    features = balagha.features(session)
    declined = {f["feature"] for f in features["not_detected"]}
    assert "taqdim / ta'khir" in declined
    assert all(f["why"] for f in features["not_detected"])


# --- WP-30: the naskh registry --------------------------------------------


def test_a_claim_without_a_claimant_is_refused(session):
    with pytest.raises(NaskhError, match="claimant"):
        naskh.record(
            session,
            abrogated_ref="2:106",
            claimant="  ",
            source_work="al-Nasikh wa-al-Mansukh",
        )


def test_a_claim_without_a_source_work_is_refused(session):
    with pytest.raises(NaskhError, match="name the work"):
        naskh.record(
            session, abrogated_ref="2:106", claimant="al-Suyuti", source_work=""
        )


def test_an_ayah_is_never_reported_as_abrogated_only_as_claimed(session):
    """There is no ``is_abrogated`` field, and there must not be one: the
    classical lists disagree about nearly every case."""
    payload = naskh.for_ayah(session, 2, 106)
    assert "is_abrogated" not in payload
    assert "claimed_abrogated_by" in payload
    assert "claims with claimants, not a status" in payload["framing"]


def test_a_recorded_claim_keeps_its_dissenters(session):
    claim = naskh.record(
        session,
        abrogated_ref="2:180",
        abrogating_ref="4:11",
        claimant="Ibn Salama",
        source_work="al-Nasikh wa-al-Mansukh",
        basis="the inheritance verses are held to supersede the bequest verse",
        rejected_by=["al-Shafi'i (partial)", "several later Hanafis"],
    )
    assert claim["abrogated"] == "2:180"
    assert claim["abrogating"] == "4:11"
    assert claim["contested"] is True
    assert len(claim["rejected_by"]) == 2


def test_a_reference_outside_the_corpus_is_refused(session):
    with pytest.raises(NaskhError, match="not an ayah"):
        naskh.record(
            session,
            abrogated_ref="2:9999",
            claimant="al-Suyuti",
            source_work="al-Itqan",
        )


# --- WP-34 acceptance: the offer rides along with every pattern view -------


def test_a_cooccurrence_result_carries_the_background_question(session):
    """A pattern result read without asking "is this just Arabic?" is a pattern
    result that will be read as Qur'anic. So the question travels with it."""
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        payload = client.get(
            "/analytics/cooccurrence", params={"root_a": "صبر", "root_b": "صلو"}
        ).json()
    offer = payload["background_check"]
    assert offer["corpus"] == "hadith"
    assert "transfer/pair" in offer["endpoint"]


def test_the_background_comparison_can_be_run_inline(session):
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        payload = client.get(
            "/analytics/cooccurrence",
            params={"root_a": "صبر", "root_b": "صلو", "background": "true"},
        ).json()
    assert payload["background_check"]["verdict"]
    # Same machinery as the finding it is checking, not a friendlier test.
    assert payload["background_check"]["quran"]["significance"]["test"] == "binomial"
