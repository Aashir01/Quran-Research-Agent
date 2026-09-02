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

    Not tidiness. ``naskh.registry`` reports that it ships empty and the ahkam
    module refuses to render a ruling partly on the strength of how many
    positions are stored — a test row left behind would make both statements
    false in the running app. Their emptiness is a design position, not an
    accident of seeding.
    """
    from sqlalchemy import func, select

    from qra.models import (
        IjazClaim,
        MadhhabPosition,
        NaskhClaim,
        SandboxSession,
        SandboxTest,
    )

    high = {
        model: session.scalar(select(func.max(model.id))) or 0
        for model in (
            SandboxSession,
            SandboxTest,
            NaskhClaim,
            MadhhabPosition,
            IjazClaim,
        )
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


def test_a_shift_reports_whole_words_not_fragments(session):
    """Only some of a word's segments carry person. Joining just those would
    report قَالُوٓا as the single letter of its subject pronoun — a correct
    comparison rendered as nonsense."""
    result = balagha.iltifat(session, surah=2, limit=60)
    for candidate in result["candidates"]:
        assert len(candidate["from_word"]) > 1, candidate
        assert len(candidate["to_word"]) > 1, candidate
    shift = next(c for c in result["candidates"] if c["ref"] == "2:3")
    assert shift["from_word"] == "وَيُقِيمُونَ"
    assert shift["to_word"] == "رَزَقۡنَٰهُمۡ"


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


# --- WP-28: semantic fields ------------------------------------------------


def test_a_field_never_calls_a_neighbour_a_synonym(session):
    """The classical result in distributional semantics is that antonyms share
    distributions. هدي's nearest neighbour in this corpus is ضلل. So the word
    'synonym' must not appear as a label anywhere in the payload."""
    from qra.analytics import fields

    payload = fields.field(session, "hidayah")
    labels = {n["relation"] for n in payload["distributional_neighbours"]}
    labels |= {n["relation"] for n in payload["most_juxtaposed"]}
    assert "synonym" not in " ".join(labels)
    assert "not synonyms" in payload["warning"]


def test_opposites_surface_as_the_most_juxtaposed(session):
    """حق/باطل and هدي/ضلل are the canonical antithesis pairs. They should be
    the highest-lift neighbours, which is the signal the payload points at."""
    from qra.analytics import fields

    guidance = {n["root"] for n in fields.field(session, "hidayah")["most_juxtaposed"]}
    truth = {n["root"] for n in fields.field(session, "haqq")["most_juxtaposed"]}
    assert "ضلل" in guidance
    assert "بطل" in truth


def test_distinctions_are_not_invented_when_no_lexicon_is_loaded(session):
    """The load-bearing test for WP-28. علم versus معرفة is a lexicographic
    judgement; frequency can show two roots are used differently but never what
    the difference *is*. With no lexicon loaded the module must say so."""
    from sqlalchemy import select

    from qra.analytics import fields
    from qra.models import Edition

    loaded = session.scalars(select(Edition).where(Edition.kind == "lexicon")).all()
    payload = fields.distinctions(session, ["علم", "حكم"])
    if loaded and payload["available"]:
        assert all(
            entry.get("lexicon_entries") for entry in payload["roots"] if entry["found"]
        )
    else:
        assert payload["available"] is False
        assert "cannot be recovered from distribution" in payload["note"]
        assert all(not entry.get("lexicon_entries") for entry in payload["roots"])


def test_a_loaded_lexicon_is_quoted_with_its_citation(session):
    """The other half: when an edition *is* present the distinction is quoted.
    A synthetic edition proves the path without shipping licensed text."""
    from sqlalchemy import select

    from qra.analytics import fields
    from qra.models import Edition, LexiconEntry, Root

    edition = Edition(
        slug="test-lexicon",
        kind="lexicon",
        name="Test Lexicon",
        author="Test Author",
        language="ar",
        direction="rtl",
        # An Edition cannot exist without its citation payload — that rule is
        # what makes every quotation in the app traceable, so the fixture obeys
        # it rather than working around it.
        source_url="local://tests/test_analysis.py",
        license="test fixture, not distributed",
        license_status="unknown",
    )
    session.add(edition)
    session.flush()
    root = session.scalar(select(Root).where(Root.root_display == "علم"))
    session.add(
        LexiconEntry(
            edition_id=edition.id,
            root_id=root.id,
            headword="علم",
            text="knowledge that admits of no doubt, distinguished from معرفة",
            reference="i. 2138",
        )
    )
    session.commit()
    try:
        payload = fields.distinctions(session, ["علم"])
        assert payload["available"] is True
        entry = payload["roots"][0]["lexicon_entries"][0]
        assert entry["reference"] == "i. 2138"
        assert entry["edition"] == "Test Lexicon"
    finally:
        session.query(LexiconEntry).filter(LexiconEntry.edition_id == edition.id).delete()
        session.query(Edition).filter(Edition.id == edition.id).delete()
        session.commit()


# --- WP-32: life domains ---------------------------------------------------


def test_every_declared_domain_root_exists_in_the_morphology(session):
    """WP-32's acceptance. A root list that silently loses an entry produces a
    verse set that is wrong and looks entirely normal."""
    from qra.analytics import domains

    report = domains.verify(session)
    assert report["all_verified"], [e for e in report["report"] if not e["verified"]]
    assert report["domains"] == len(domains.DOMAINS)


def test_a_domain_verse_set_counts_the_same_from_both_directions(session):
    """Exhaustive retrieval means the forward walk and the reverse scan agree.
    This is where that stops being an assumption."""
    from qra.analytics import domains

    for slug in ("economics", "family", "environment"):
        check = domains.exhaustiveness(session, slug)
        assert check["agree"], check


def test_a_missing_root_raises_rather_than_shortening_the_list(session):
    from qra.analytics import domains
    from qra.analytics.domains import Domain, DomainError

    broken = Domain(
        slug="broken", label_en="Broken", label_ar="", roots=("علم", "zzzz"), note=""
    )
    with pytest.raises(DomainError, match="absent from the morphology"):
        domains._ayat_for(session, broken)


def test_the_domains_do_not_pretend_to_partition_the_corpus(session):
    from qra.analytics import domains

    catalogue = domains.catalogue(session)
    summed = sum(entry["ayat"] for entry in catalogue["domains"])
    assert summed > catalogue["ayat_covered"]
    assert "double-counts" in catalogue["overlap_note"]


def test_the_legal_vocabulary_is_madani_weighted(session):
    """A check that the machinery measures something real: transactional verses
    concentrate in the Medinan period, which is uncontroversial history."""
    from qra.analytics import domains

    revelation = domains.domain(session, "economics")["revelation"]
    assert revelation["significance"]["within_chance"] is False
    assert revelation["significance"]["direction"] == "fewer"


# --- WP-26: nazm and rings -------------------------------------------------


def test_a_segmentation_is_labelled_a_suggestion(session):
    from qra.analytics import nazm

    layout = nazm.segment(session, 12)
    assert layout["provenance"] == "system_suggested"
    assert len(layout["passages"]) > 1
    assert "a reading" in layout["caveat"]


def test_a_short_surah_is_not_cut_into_pieces_the_method_cannot_support(session):
    from qra.analytics import nazm

    layout = nazm.segment(session, 108)
    assert len(layout["passages"]) == 1
    assert "interior" in layout["note"]


def test_a_ring_claim_is_scored_against_a_shuffled_null(session):
    """WP-26's acceptance. Chiastic readings are easy to construct, so a mirror
    score means nothing without knowing what a shuffled surah produces."""
    from qra.analytics import nazm

    result = nazm.rings(session, 12, trials=100)
    assert result["testable"] is True
    assert result["trials"] == 100
    assert result["null_mean"] > 0
    # Add-one: a finite permutation test cannot support a p of exactly zero.
    assert result["p_value"] > 0
    assert result["provenance"] == "system_suggested"
    assert "conservative" in result["null_model_limitation"]


def test_too_few_passages_is_refused_rather_than_scored(session):
    from qra.analytics import nazm

    result = nazm.rings(session, 108, trials=50)
    assert result["testable"] is False


def test_the_ring_sweep_states_its_own_chance_rate(session):
    from qra.analytics import nazm

    sweep = nazm.sweep(session, min_ayat=40, trials=60)
    assert "would clear p<0.05 by chance alone" in sweep["headline"]
    assert sweep["expected_by_chance"] == round(sweep["surahs_tested"] * 0.05, 1)
    assert sweep["surviving_correction"] <= sweep["beyond_chance_uncorrected"]


# --- WP-29: ayat al-ahkam --------------------------------------------------


def test_a_legal_topic_never_renders_a_ruling(session):
    """WP-29's acceptance, enforced rather than advised: `ruling` is null until
    more than one school is on record, and it says which case applies."""
    from qra.analytics import ahkam

    topic = ahkam.topic(session, "mirath")
    assert topic["ruling"] is None
    assert topic["why_no_ruling"]
    assert topic["ayat_also_carrying_a_legal_marker"] > 0


def test_one_recorded_position_still_does_not_produce_a_ruling(session):
    """The dangerous case. One position on record is exactly when a tool is
    tempted to show it as the answer."""
    from qra.analytics import ahkam

    ahkam.record_position(
        session,
        topic="mirath",
        madhhab="hanafi",
        position="test position, single school",
        source_work="Test Work",
    )
    topic = ahkam.topic(session, "mirath")
    assert topic["ruling"] is None
    assert topic["schools_on_record"] == ["hanafi"]
    assert "fatwa engine" in topic["why_no_ruling"]

    ahkam.record_position(
        session,
        topic="mirath",
        madhhab="shafii",
        position="test position, second school",
        source_work="Test Work",
    )
    topic = ahkam.topic(session, "mirath")
    assert topic["ruling"] is None
    assert len(topic["schools_on_record"]) == 2
    assert "not resolved into one answer" in topic["why_no_ruling"]


def test_a_position_without_a_source_is_refused(session):
    from qra.analytics import ahkam
    from qra.analytics.ahkam import AhkamError

    with pytest.raises(AhkamError, match="name the work"):
        ahkam.record_position(
            session, topic="mirath", madhhab="maliki", position="a position", source_work=" "
        )


def test_the_legal_marker_reads_the_right_morphology_column(session):
    """IMPV is an aspect value here, not a mood. Reading it from the mood column
    returns zero and looks exactly like 'the Qur'an contains no imperatives'."""
    from qra.analytics import ahkam

    survey = ahkam.survey(session)
    assert survey["markers"]["imperative"] > 1000
    assert survey["markers"]["jussive"] > 500


def test_the_ahkam_survey_reports_the_disagreement_about_the_count(session):
    from qra.analytics import ahkam

    survey = ahkam.survey(session)
    assert survey["classical_estimates"]["range"] == [150, 500]
    assert "the total is the disagreement" in survey["classical_estimates"]["note"]


# --- WP-31: i'jaz dossiers -------------------------------------------------


@pytest.fixture
def seeded_ijaz(session):
    from qra.analytics import ijaz

    ijaz.seed(session)
    return ijaz


def test_ten_circulating_claims_produce_balanced_dossiers(session, seeded_ijaz):
    """WP-31's acceptance. Each dossier carries the claim, the verse, what the
    Arabic must mean for it to hold, and the classical reading — not a verdict."""
    from qra.analytics.ijaz import SEEDS

    assert len(SEEDS) == 10
    for spec in SEEDS:
        dossier = seeded_ijaz.dossier(session, spec.slug)
        assert dossier["verse"]["text_uthmani"]
        assert dossier["requires_the_arabic_to_mean"]
        assert dossier["science_status"]
        assert dossier["semantic_load"]["found"] is True
        assert "does not endorse or refute" in dossier["stance"]


def test_no_claim_can_be_stored_above_l3(session, seeded_ijaz):
    """The hard block. The database constraint, not a convention."""
    from sqlalchemy.exc import IntegrityError

    from qra.models import IjazClaim

    levels = {row.level for row in session.query(IjazClaim).all()}
    assert levels <= {"L3", "L4"}

    session.add(
        IjazClaim(slug="forbidden-level", claim="x", ayah_id=1, level="L0")
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_the_module_has_no_path_that_invents_a_claim(session, seeded_ijaz):
    from qra.analytics.ijaz import IjazError

    with pytest.raises(IjazError, match="no path that creates one"):
        seeded_ijaz.dossier(session, "a-claim-nobody-made")


def test_unattributed_fields_are_named_rather_than_filled(session, seeded_ijaz):
    """'Commonly attributed to' is how fabricated provenance enters. Where the
    proponent is not known to this project the field is empty and listed."""
    dossier = seeded_ijaz.dossier(session, "iron-sent-down")
    assert dossier["proponent"] is None
    assert "proponent" in dossier["unsourced"]

    sourced = seeded_ijaz.dossier(session, "expanding-universe")
    assert sourced["proponent"]
    assert "proponent" not in sourced["unsourced"]


def test_the_semantic_load_check_shows_the_senses_the_claim_competes_with(
    session, seeded_ijaz
):
    """The check WP-31 asks for. أنزل is used of scripture, rain, cattle and
    clothing, so 'physical descent from space' is one reading among many — and
    that is visible from the corpus rather than argued."""
    dossier = seeded_ijaz.dossier(session, "iron-sent-down")
    load = dossier["semantic_load"]
    assert load["total_segments"] > 250
    assert load["distinct_lemmas"] > 3
    assert any(sense["lemma"].startswith("أَنزَل") for sense in load["senses"])


def test_a_rare_root_is_flagged_as_thin_evidence(session, seeded_ijaz):
    """رتق occurs once in the whole Qur'an. A claim resting on it has almost
    nothing internal to check against, and the payload says so."""
    load = seeded_ijaz.semantic_load(session, "رتق")
    assert load["total_segments"] <= 10
    assert "very little internal evidence" in load["reading"]


def test_the_classical_reading_is_quoted_not_summarised(session, seeded_ijaz):
    """Paraphrasing a mufassir from memory is the same fabrication as inventing
    scripture, one step further from the text."""
    dossier = seeded_ijaz.dossier(session, "iron-sent-down")
    entries = dossier["classical_understanding"]["entries"]
    assert entries
    assert all(entry["citation"] and entry["text"] for entry in entries)
    assert any("Tabari" in entry["edition"] for entry in entries)
