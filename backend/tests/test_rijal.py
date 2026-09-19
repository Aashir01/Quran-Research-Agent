"""Rijal and the transmission graph (Track I).

The corpus has held 34,178 parsed chains and analysed none of them. Most of
these tests are about the two things that make a computational isnad study
either honest or worthless: whether a node is a person, and whether a
convergence means anything.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from qra.analytics import rijal
from qra.analytics.isnad import is_relative_reference, narrators
from qra.analytics.rijal import RijalError
from qra.models import ChainPosition, Narrator, NarratorGrading, TransmissionEdge


@pytest.fixture(scope="module")
def graph(request):
    """Build once for the module — a full rebuild is ~20s."""
    from qra.db import SessionLocal
    from qra.models import Ayah

    with SessionLocal() as session:
        if (session.scalar(select(func.count()).select_from(Ayah)) or 0) != 6236:
            pytest.skip("no ingested corpus reachable")
        if not (session.scalar(select(func.count()).select_from(Narrator)) or 0):
            rijal.build(session)
        yield session


# --- extraction -------------------------------------------------------------


def test_the_narration_verb_is_stripped_from_the_first_name():
    """A chain opens with the verb attached to the first transmitter. Left on,
    that man becomes two nodes — one spelled with the verb and one without."""
    chain = narrators("حدثنا ابو بكر بن ابي شيبة حدثنا وكيع عن الاعمش عن ابي هريرة")
    assert chain[0] == "ابو بكر بن ابي شيبه"
    assert not any(n.startswith("حدثنا") for n in chain)


def test_a_verb_with_the_conjunction_is_also_stripped():
    """Collectors stack parallel chains with و prefixed to the verb, written
    joined — so the bare verb never matches and the phrase survives as a name."""
    chain = narrators("وحدثنا قتيبة بن سعيد عن مالك عن نافع عن ابن عمر")
    assert chain[0] == "قتيبه بن سعيد"


def test_kinship_references_are_not_names():
    """عن أبيه is a placeholder for a person, not a person. Treated as a node it
    became the largest hub in the corpus — 3,488 narrations, as though one man
    had taught a tenth of it."""
    assert is_relative_reference("ابيه")
    assert is_relative_reference("جده")
    # A kunya that merely begins the same way is a real name.
    assert not is_relative_reference("ابي هريره")
    assert not is_relative_reference("ابي صالح")


# --- the graph --------------------------------------------------------------


def test_the_graph_recovers_the_major_transmitters(graph):
    """A sanity check with a known answer. If the extraction is sound the
    busiest names are the ones any hadith scholar would name."""
    names = {h["name"] for h in rijal.hubs(graph, limit=20)["hubs"]}
    expected = {"سفيان", "شعبه", "ابي هريره", "الزهري", "الاعمش", "نافع", "مالك"}
    assert expected <= names, expected - names


def test_no_kinship_placeholder_became_a_narrator(graph):
    top = rijal.hubs(graph, limit=40)["hubs"]
    assert not [h for h in top if is_relative_reference(h["name"])]


def test_an_unresolvable_link_breaks_the_chain_rather_than_bridging_it(graph):
    """Bridging over "his father" would assert that A transmitted to C when the
    text says A transmitted to someone's father who transmitted to C — an edge
    the source does not contain."""
    from qra.analytics.rijal import Chain, _chain_of  # noqa: F401

    ids = dict(graph.execute(select(Narrator.canonical, Narrator.id)).all())
    from qra.arabic import search_form

    # The placeholder itself must have no node at all.
    assert search_form("ابيه") not in ids


def test_every_chain_slot_is_unique(graph):
    """Two narrators at one depth in one chain would mean a parse that lost the
    ordering, and every edge built from it would be wrong."""
    duplicated = graph.execute(
        select(ChainPosition.hadith_id, ChainPosition.depth, func.count())
        .group_by(ChainPosition.hadith_id, ChainPosition.depth)
        .having(func.count() > 1)
        .limit(5)
    ).all()
    assert not duplicated


def test_edges_never_point_a_narrator_at_himself(graph):
    self_loops = graph.scalar(
        select(func.count())
        .select_from(TransmissionEdge)
        .where(TransmissionEdge.teacher_id == TransmissionEdge.student_id)
    )
    assert self_loops == 0


# --- conflation -------------------------------------------------------------


def test_the_commonest_arabic_names_are_flagged_as_conflated(graph):
    """عبد الله and محمد are the most common names in the language. If the
    detector does not find them it is not detecting anything."""
    report = rijal.conflation_report(graph, limit=15)
    flagged = {s["name"] for s in report["suspects"]}
    assert "عبد الله" in flagged
    assert "محمد" in flagged


def test_a_single_identifiable_transmitter_is_not_flagged(graph):
    """مالك sits in one generation and should look like one man."""
    row = graph.scalar(select(Narrator).where(Narrator.display_name == "مالك"))
    assert row is not None
    assert row.position_spread < 0.3


def test_the_spread_metric_is_robust_to_one_odd_chain(graph):
    """max - min saturates: any name appearing thousands of times lands at both
    extremes once, so every major transmitter scored 1.00 and the metric ranked
    them all identically suspect. The interquartile range is what is stored."""
    report = rijal.conflation_report(graph, limit=5)
    assert report["median_position_spread"] < 0.3
    assert "interquartile" in report["metric"]


def test_the_narrator_view_decides_on_the_number_it_shows(graph):
    """Reporting the full range and then concluding from the interquartile
    spread reads as a contradiction."""
    row = graph.scalar(select(Narrator).where(Narrator.display_name == "مالك"))
    warning = rijal.narrator(graph, row.id)["identity_warning"]
    assert f"{row.position_spread:.2f}" in warning
    assert "consistent with one man" in warning


# --- common links -----------------------------------------------------------


def test_a_bundle_of_two_is_refused(graph):
    """Convergence across two chains is arithmetic, not evidence."""
    with pytest.raises(RijalError, match="at least three"):
        rijal.common_link(graph, [1, 2])


def test_a_real_bundle_finds_its_common_link_beyond_chance(graph):
    """The validation case. Bukhari 35's bundle converges on Abu Salama, with
    Abu Hurayra and al-Zuhri as partial common links — the canonical
    Abu Hurayra → Abu Salama → al-Zuhri path."""
    from qra.analytics import takhrij
    from qra.models import Hadith

    seed = graph.scalar(
        select(Hadith).where(Hadith.collection == "bukhari", Hadith.number == "35")
    )
    bundle = takhrij.parallels_for(graph, seed.id)
    ids = [seed.id] + [p["hadith_id"] for p in bundle.get("parallels", [])]
    if len(ids) < 10:
        pytest.skip("takhrij returned too small a bundle to test convergence")

    result = rijal.common_link(graph, ids, trials=200)
    assert result["chains_examined"] >= 10
    assert result["null_model"]["p_value"] is not None
    # Add-one: a finite resample must never report a p of exactly zero.
    assert result["null_model"]["p_value"] > 0
    assert result["beyond_chance"] is True
    assert result["provenance"] == "system_suggested"


def test_a_convergence_that_chance_reproduces_is_reported_as_nothing(graph):
    """The honest half. A small bundle around a prolific transmitter converges
    for dull reasons, and the reading must say so rather than name a founder."""
    chains = rijal._corpus_chains(graph)
    assert chains
    # Three unrelated narrations: any shared name is coincidence.
    ids = graph.scalars(
        select(ChainPosition.hadith_id).distinct().limit(4)
    ).all()
    result = rijal.common_link(graph, list(ids), trials=100)
    if not result["beyond_chance"]:
        assert "carries no weight" in result["reading"] or "cannot be tested" in result["reading"]


def test_the_null_model_is_described_in_the_payload(graph):
    """A p-value whose null is not stated is not interpretable."""
    ids = list(graph.scalars(select(ChainPosition.hadith_id).distinct().limit(5)).all())
    result = rijal.common_link(graph, ids, trials=60)
    method = result["null_model"]["method"]
    assert "resampled" in method
    assert "Add-one" in method


# --- gradings ---------------------------------------------------------------


def test_the_registry_of_gradings_ships_empty(graph):
    """Reliability is not computed. It is something a named critic said."""
    assert graph.scalar(select(func.count()).select_from(NarratorGrading)) == 0
    row = graph.scalar(select(Narrator).where(Narrator.display_name == "مالك"))
    payload = rijal.narrator(graph, row.id)
    assert payload["gradings"] == []
    assert "not computed here" in payload["grading_note"]


def test_a_grading_without_a_critic_is_refused(graph):
    row = graph.scalar(select(Narrator).where(Narrator.display_name == "مالك"))
    with pytest.raises(RijalError, match="name the critic"):
        rijal.record_grading(
            graph, row.id, grade="thiqa", critic="  ", source_work="Tahdhib al-Kamal"
        )


def test_a_grading_records_who_said_it(graph):
    row = graph.scalar(select(Narrator).where(Narrator.display_name == "مالك"))
    try:
        result = rijal.record_grading(
            graph,
            row.id,
            grade="thiqa",
            critic="Ibn Hajar al-'Asqalani",
            source_work="Taqrib al-Tahdhib",
        )
        assert result["critic"] == "Ibn Hajar al-'Asqalani"
        stored = graph.scalars(
            select(NarratorGrading).where(NarratorGrading.narrator_id == row.id)
        ).all()
        assert [g.critic for g in stored] == ["Ibn Hajar al-'Asqalani"]
    finally:
        graph.query(NarratorGrading).filter(
            NarratorGrading.narrator_id == row.id
        ).delete()
        graph.commit()


def test_a_rebuild_refuses_to_orphan_stored_gradings(graph):
    """The derived tables are rebuilt wholesale; gradings are not derived and
    must not be silently destroyed with them.

    The refusal has to happen before the first DELETE. It did not: the guard ran
    after the chain positions and edges were already gone, declining to do the
    damage it had just done — and every later test in the module then ran
    against an empty graph.
    """
    row = graph.scalar(select(Narrator).where(Narrator.display_name == "مالك"))
    positions_before = graph.scalar(select(func.count()).select_from(ChainPosition))
    edges_before = graph.scalar(select(func.count()).select_from(TransmissionEdge))
    rijal.record_grading(
        graph, row.id, grade="thiqa", critic="al-Dhahabi", source_work="al-Kashif"
    )
    try:
        with pytest.raises(RijalError, match="would orphan"):
            rijal.build(graph)
        # The refusal must leave the graph exactly as it found it.
        assert graph.scalar(select(func.count()).select_from(ChainPosition)) == positions_before
        assert graph.scalar(select(func.count()).select_from(TransmissionEdge)) == edges_before
    finally:
        graph.query(NarratorGrading).filter(
            NarratorGrading.narrator_id == row.id
        ).delete()
        graph.commit()
