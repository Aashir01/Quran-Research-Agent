"""The uncertainty audit (Track H).

The application's rule is that a number never travels alone. That rule is kept
by review, and review is the mechanism that decays — the twentieth analytic
added in a hurry is the one that returns a bare integer. This checks it
structurally, and these tests check the checker.
"""

from __future__ import annotations

from qra import audit as audit_mod
from qra.audit import _has_baseline, audit


def test_every_analytic_surface_carries_its_baseline(session):
    report = audit(session)
    flagged = [r for r in report["results"] if not r["ok"]]
    assert not flagged, [(r["surface"], r["findings"], r["error"]) for r in flagged]


def test_a_surface_that_cannot_run_is_flagged_not_passed(session):
    """An unrunnable surface has demonstrated nothing. Passing it would make the
    audit get greener as the code rotted."""
    from qra.audit import Surface

    def explode(_session):
        raise RuntimeError("surface is broken")

    original = audit_mod.SURFACES
    audit_mod.SURFACES = lambda: (Surface("broken", explode),)
    try:
        report = audit(session)
    finally:
        audit_mod.SURFACES = original

    assert report["flagged"] == 1
    assert "surface is broken" in report["results"][0]["error"]


def test_the_audit_detects_a_bare_count(session):
    """A planted violation, so the audit is known to be capable of failing."""
    from qra.audit import Surface

    original = audit_mod.SURFACES
    audit_mod.SURFACES = lambda: (
        Surface("bare", lambda _s: {"occurrences": 42, "rows": [1, 2, 3]}),
    )
    try:
        report = audit(session)
    finally:
        audit_mod.SURFACES = original

    rules = {f["rule"] for f in report["results"][0]["findings"]}
    assert "count without a baseline" in rules


def test_a_null_baseline_does_not_count():
    """`balagha.iltifat` carried `share_of_scope`, which is None whenever the
    query is scoped to one surah. The key was there and the baseline was not,
    and the surface passed on the strength of the key alone."""
    from qra.audit import _walk

    assert _walk({"total": 5, "share_of_scope": None}) == {"total"}
    assert "share_of_scope" in _walk({"total": 5, "share_of_scope": 0.55})


def test_a_raw_shared_count_is_not_mistaken_for_a_proportion():
    """`share` is matched as an exact key, not a substring, so `shared_units`
    and `shared_ayat` — which are counts — cannot launder a payload."""
    assert not _has_baseline({"shared_units", "shared_ayat", "units_both"})
    assert _has_baseline({"share"})


def test_the_audit_says_what_it_is_not(session):
    """Calibration needs labelled outcomes this corpus does not have. Claiming
    to audit it anyway would be the error the audit exists to catch."""
    scope = audit(session)["scope"]
    assert "not calibration" in scope
    assert "labelled" in scope


def test_iltifat_reports_its_baseline_even_when_scoped(session):
    """The gap the audit actually found: a researcher looking at one surah got
    a raw shift count with nothing saying half the corpus has one."""
    from qra.analytics import balagha

    scoped = balagha.iltifat(session, surah=2, limit=5)
    assert scoped["corpus_baseline_rate"] > 0.4
    assert "whole corpus" in scoped["baseline_note"]


def test_a_legal_topic_reports_what_its_count_should_be_read_against(session):
    from qra.analytics import ahkam

    topic = ahkam.topic(session, "mirath")
    assert topic["corpus_ayat_with_any_legal_marker"] > 1000
    assert topic["expected_if_markers_were_independent"] > 0


def test_the_hub_list_admits_it_is_a_slice(session):
    from sqlalchemy import select

    from qra.analytics import rijal
    from qra.models import Narrator

    if not session.scalar(select(Narrator.id).limit(1)):
        import pytest

        pytest.skip("transmission graph not built")
    hubs = rijal.hubs(session, limit=5)
    assert hubs["exhaustive"] is False
    assert hubs["returned"] == 5
    assert hubs["narrators_total"] > 5
    assert all("share_of_all_positions" in h for h in hubs["hubs"])
