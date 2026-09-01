"""Takhrij and the isnad split (WP-21).

These need the corpus, so they skip cleanly without one. What they assert is
that the module is honest about a heuristic sitting underneath an exhaustive
comparison — the split can be wrong, and every result says how much to trust it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from qra.analytics import takhrij
from qra.analytics.isnad import RELIABLE_SPLIT, narrators, split
from qra.models import Hadith

# --- the split -------------------------------------------------------------


def test_a_chain_is_separated_from_the_report(session):
    """Bukhari 109 is short and its boundary is unambiguous: the matn is the
    Prophet's words, and none of the chain should survive into it."""
    row = session.scalar(
        select(Hadith).where(Hadith.collection == "bukhari", Hadith.number == "109")
    )
    if row is None:
        pytest.skip("bukhari 109 not in this corpus")
    parsed = split(row.text_ar)
    assert parsed.confidence > 0
    assert "حَدَّثَنَا" not in parsed.matn, "a transmission verb leaked into the matn"
    assert "مَقْعَدَهُ" in parsed.matn or "النَّارِ" in parsed.matn


def test_an_unsplittable_row_returns_everything_as_matn(session):
    """Never a fabricated boundary. A row with no chain marker comes back whole,
    at confidence zero, so downstream code can tell it apart."""
    parsed = split("قال هذا نص بغير إسناد ولا رواة معروفين في هذه الرواية")
    assert parsed.confidence == 0.0
    assert parsed.isnad == ""
    assert parsed.matn


def test_the_split_never_swallows_the_whole_report(session):
    """The failure that would quietly break takhrij: an empty matn matches
    everything."""
    rows = session.scalars(
        select(Hadith).where(Hadith.text_ar.is_not(None)).limit(400)
    ).all()
    for row in rows:
        parsed = split(row.text_ar)
        assert parsed.matn.strip(), f"{row.collection} {row.number} produced an empty matn"


def test_most_of_the_corpus_splits_reliably(session):
    """A heuristic that works on a handful of rows is not a corpus tool."""
    rows = session.scalars(
        select(Hadith).where(Hadith.text_ar.is_not(None)).limit(2000)
    ).all()
    reliable = sum(1 for row in rows if split(row.text_ar).confidence >= RELIABLE_SPLIT)
    assert reliable / len(rows) > 0.6, f"only {reliable}/{len(rows)} split reliably"


def test_narrators_come_out_in_transmission_order():
    chain = "حدثنا عبد الله بن يوسف قال أخبرنا مالك عن هشام بن عروة عن أبيه"
    names = narrators(chain)
    assert len(names) >= 3
    assert any("مالك" in n for n in names)
    assert names.index(next(n for n in names if "مالك" in n)) < len(names) - 1


# --- matching --------------------------------------------------------------


@pytest.fixture(scope="module")
def index(request):
    from sqlalchemy import func

    from qra.db import SessionLocal

    with SessionLocal() as s:
        if (s.scalar(select(func.count()).select_from(Hadith)) or 0) < 100:
            pytest.skip("no hadith corpus ingested")
        return takhrij.build_index(s)


def test_a_known_cross_collection_parallel_is_found(session, index):
    """Bukhari 1825 and Muslim 2525 carry the same narration about Quraysh and
    Ashura. If takhrij cannot find that pair it is not doing its job."""
    row = session.scalar(
        select(Hadith).where(Hadith.collection == "bukhari", Hadith.number == "1825")
    )
    if row is None:
        pytest.skip("bukhari 1825 not in this corpus")
    result = takhrij.parallels_for(session, row.id, index=index)
    refs = [p["ref"] for p in result["parallels"]]
    assert any(ref.startswith("muslim") for ref in refs), refs


def test_matching_is_symmetric(session, index):
    """If A is a parallel of B at score s, B is a parallel of A at score s.
    An asymmetric similarity would make results depend on where you started."""
    a = session.scalar(
        select(Hadith).where(Hadith.collection == "bukhari", Hadith.number == "1825")
    )
    b = session.scalar(
        select(Hadith).where(Hadith.collection == "muslim", Hadith.number == "2525")
    )
    if a is None or b is None:
        pytest.skip("pair not in this corpus")
    forward = {p["ref"]: p["score"] for p in takhrij.parallels_for(session, a.id, index=index)["parallels"]}
    backward = {p["ref"]: p["score"] for p in takhrij.parallels_for(session, b.id, index=index)["parallels"]}
    assert forward.get("muslim 2525") == backward.get("bukhari 1825")


def test_an_unreliable_split_caps_the_band(session, index):
    """A score computed over chain words is not evidence about the report, so a
    parallel whose split failed can never be reported as strong."""
    rows, _ = index
    weak = [r for r in rows.values() if r.compared == "whole_row"]
    if not weak:
        pytest.skip("every row split reliably")
    result = takhrij.parallels_for(session, weak[0].id, index=index)
    assert all(p["band"] == "possible" for p in result["parallels"])


def test_every_parallel_carries_its_own_grading(session, index):
    """The point of the module: a narration sahih in one collection and da'if in
    another is a fact to show, not a contradiction to resolve."""
    rows, _ = index
    for row_id in list(rows)[:60]:
        result = takhrij.parallels_for(session, row_id, index=index)
        for parallel in result["parallels"]:
            assert "grading" in parallel and parallel["grading"]
        if result["parallels"]:
            assert "caveat" in result
            return
    pytest.skip("no parallels in the sampled rows")
