"""WP-03, WP-05, WP-06, WP-60: jobs, budgets, cache and operations."""

import time

import pytest

from qra import cache
from qra.budget import BudgetExceeded, RunBudget, budget_for, monthly_usage
from qra.jobs import backend, cancel, enqueue, job_status
from qra.ops import SlidingWindowLimiter, readiness

# --- WP-03 -----------------------------------------------------------------


def test_job_reports_progress_while_running():
    def work(session, handle):
        for i in range(10):
            handle.checkpoint()
            handle.report(i + 1, 10, stage="sweeping")
            time.sleep(0.02)
        return {"ok": True}

    job = enqueue("test-progress", work)
    time.sleep(0.08)
    mid = job_status(job["id"])
    assert mid["status"] in ("running", "complete")
    assert mid["progress"]["total"] == 10
    for _ in range(60):
        if job_status(job["id"])["status"] == "complete":
            break
        time.sleep(0.05)
    assert job_status(job["id"])["result"] == {"ok": True}


def test_a_running_job_can_be_cancelled():
    def forever(session, handle):
        for i in range(500):
            handle.checkpoint()
            handle.report(i, 500)
            time.sleep(0.01)
        return {"never": True}

    job = enqueue("test-cancel", forever)
    time.sleep(0.05)
    cancel(job["id"])
    for _ in range(60):
        if job_status(job["id"])["status"] == "cancelled":
            break
        time.sleep(0.05)
    assert job_status(job["id"])["status"] == "cancelled"


def test_a_failing_job_records_the_error_not_a_result():
    def boom(session):
        raise ValueError("deliberate")

    job = enqueue("test-fail", boom)
    for _ in range(60):
        if job_status(job["id"])["status"] == "failed":
            break
        time.sleep(0.05)
    payload = job_status(job["id"])
    assert payload["status"] == "failed"
    assert "deliberate" in payload["error"]
    assert "result" not in payload


def test_backend_is_reported_honestly():
    assert backend() in ("arq", "thread")


# --- WP-05 -----------------------------------------------------------------


def test_budget_raises_before_spending_past_the_ceiling():
    budget = RunBudget(run_id="r1", ceiling_usd=0.10)
    budget.record(
        provider="p", model="m", role="planner", input_tokens=1000, output_tokens=500, cost_usd=0.08
    )
    budget.check(0.01)  # still inside
    with pytest.raises(BudgetExceeded):
        budget.check(0.05)
    assert budget.stopped_reason and "partial results" in budget.stopped_reason


def test_cached_calls_do_not_consume_budget():
    budget = RunBudget(run_id="r2", ceiling_usd=1.0)
    budget.record(provider="p", model="m", role="x", input_tokens=10, output_tokens=10,
                  cost_usd=0.5, cached=True)
    assert budget.spent_usd == 0.0
    assert budget.calls == 1


def test_budget_serialises_what_was_spent(session):
    budget = budget_for(session, "r3")
    assert budget.ceiling_usd > 0
    payload = budget.to_dict()
    assert {"ceiling_usd", "spent_usd", "remaining_usd", "exhausted"} <= set(payload)


def test_monthly_usage_returns_a_window(session):
    payload = monthly_usage(session)
    assert payload["window_days"] == 30
    assert "tokens" in payload and "cost_usd" in payload


# --- WP-06 -----------------------------------------------------------------


def test_cache_key_is_order_independent(session):
    cache.put(session, "model_call", {"a": 1, "b": 2}, "value")
    assert cache.get(session, "model_call", {"b": 2, "a": 1}) == "value"


def test_cache_refuses_kinds_it_does_not_own(session):
    cache.put(session, "deterministic_retrieval", {"root": "علم"}, "should not store")
    assert cache.get(session, "deterministic_retrieval", {"root": "علم"}) is None


def test_cache_stats_state_what_is_not_cached(session):
    payload = cache.stats(session)
    assert "deterministic retrieval" in payload["not_cached"]


# --- WP-60 -----------------------------------------------------------------


def test_rate_limiter_allows_then_blocks():
    limiter = SlidingWindowLimiter(per_minute=3)
    assert all(limiter.check("k")[0] for _ in range(3))
    allowed, retry_after = limiter.check("k")
    assert not allowed and retry_after > 0


def test_rate_limiter_is_per_key():
    limiter = SlidingWindowLimiter(per_minute=1)
    assert limiter.check("a")[0]
    assert limiter.check("b")[0]
    assert not limiter.check("a")[0]


def test_rate_limiting_can_be_disabled():
    limiter = SlidingWindowLimiter(per_minute=0)
    assert all(limiter.check("k")[0] for _ in range(100))


def test_readiness_distinguishes_itself_from_liveness(session):
    payload = readiness(session)
    assert set(payload["checks"]) >= {"corpus", "morphology", "lexical_index"}
    assert payload["checks"]["corpus"]["expected"] == 6236
