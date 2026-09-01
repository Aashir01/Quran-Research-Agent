"""Occasions of revelation as graded reports (WP-20).

The spec's line is "no asbab entry renders without its grade beside it". These
tests hold that line, and also cover the corpus bug the work package uncovered:
the shipped al-Wahidi edition is filed sequentially rather than by verse, so 673
of 690 self-citing reports sat under the wrong ayah.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from qra.analytics import asbab
from qra.models import AsbabReport, Edition


@pytest.fixture(scope="module", autouse=True)
def rebuilt():
    from qra.db import SessionLocal

    with SessionLocal() as s:
        if s.scalar(select(Edition).where(Edition.slug == "asbab-wahidi")) is None:
            pytest.skip("asbab edition not ingested")
        asbab.rebuild(s)


def test_no_report_ever_serialises_without_a_grade(session):
    """The enforcement is in serialisation, so no caller can forget it."""
    rows = session.scalars(select(AsbabReport).limit(200)).all()
    if not rows:
        pytest.skip("no asbab reports")
    for row in rows:
        payload = asbab.serialise(row)
        assert payload["grade"] in asbab.GRADES
        assert payload["grade"], "a report serialised with an empty grade"


def test_ungraded_is_stated_not_implied(session):
    """`ungraded` must not read as `weak`, and must not read as `authenticated`."""
    row = session.scalars(select(AsbabReport).where(AsbabReport.grade == "ungraded").limit(1)).first()
    if row is None:
        pytest.skip("no ungraded reports")
    payload = asbab.serialise(row)
    assert "not that it is weak" in payload["grade_note"]


def test_reports_are_reanchored_to_the_verse_they_cite(session):
    """2:113 is 'the Jews say the Christians follow nothing'. Its report was
    filed under 2:9, 'they deceive Allah' — a different verse entirely."""
    at_113 = asbab.for_ayah(session, 2, 113)
    assert at_113["count"] >= 1
    assert any("[2:113]" in report["text"] for report in at_113["reports"])

    # And it is no longer served under the verse it was wrongly filed against.
    at_9 = asbab.for_ayah(session, 2, 9)
    assert not any("[2:113]" in report["text"] for report in at_9["reports"])


def test_non_asbab_content_is_withheld_not_served(session):
    """The upstream feed mixes in mystical commentary. Serving that as an
    occasion of revelation would present exegesis as history."""
    withheld = session.scalars(
        select(AsbabReport).where(AsbabReport.status == "withheld").limit(1)
    ).first()
    assert withheld is not None, "nothing was withheld — the classifier is not running"
    assert withheld.withheld_reason
    published = asbab.for_ayah(session, withheld.surah_id or 1, withheld.ayah_num or 1)
    assert withheld.id not in [r["id"] for r in published["reports"]]


def test_a_mapping_from_upstream_filing_is_marked_uncertain(session):
    """The filing is demonstrably unreliable for this edition, so anything
    resting on it says so rather than inheriting the confidence of a real
    citation."""
    row = session.scalars(
        select(AsbabReport).where(AsbabReport.mapping == "upstream_filing").limit(1)
    ).first()
    if row is None:
        pytest.skip("every report self-cites")
    payload = asbab.serialise(row)
    assert payload["mapping_confidence"] < 0.5
    assert "uncertain" in payload["mapping_note"]


def test_coverage_is_reported_and_low(session):
    """Most of the Qur'an has no transmitted occasion. Overstating coverage
    would be inventing history."""
    payload = asbab.coverage(session)
    assert payload["corpus_ayat"] == 6236
    assert 0 < payload["coverage_pct"] < 25
    assert "inventing history" in payload["note"]


def test_asbab_no_longer_leaks_into_commentary(session):
    """It has its own endpoint with grades now. Letting it through the tafsir
    path would restore both halves of the original bug."""
    from qra.tools import get_tafsir

    result = get_tafsir(session, 2, 9)
    assert "asbab-wahidi" not in [entry["edition"] for entry in result["entries"]]


def test_rebuild_is_idempotent(session):
    before = asbab.rebuild(session)
    after = asbab.rebuild(session)
    assert before["written"] == after["written"]
    assert before["published"] == after["published"]
