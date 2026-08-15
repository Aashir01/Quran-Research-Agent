"""The golden eval set, run as part of the ordinary test suite.

Ground-truth failures are hard failures: they mean a published root frequency,
a structural total or a product contract no longer holds. Regression items are
reported separately by `qra eval` and are not asserted here, because a change
in them is a question for a human, not automatically a bug.
"""

import pytest

from qra.eval import load_items, run_eval


def test_golden_set_is_well_formed():
    items = load_items()
    assert len(items) >= 50
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "duplicate eval ids"
    for item in items:
        assert item["tier"] in ("ground_truth", "regression")
        assert item["source_of_truth"], f"{item['id']} does not say where its truth comes from"
        assert item["kind"] and item["tool"]


def test_every_regression_item_says_it_is_not_ground_truth():
    """Guards against a recorded value quietly being read as a verified one."""
    for item in load_items():
        if item["tier"] == "regression":
            assert "recorded from this system" in item["source_of_truth"]


@pytest.mark.slow
def test_ground_truth_holds(session):
    report = run_eval(session, tier="ground_truth")
    failures = [r for r in report["results"] if not r["passed"]]
    assert not failures, "\n".join(
        f"{r['id']}: expected {r['expected']!r}, got {r['actual']!r} ({r['detail']})"
        for r in failures
    )
