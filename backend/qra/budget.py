"""Cost and quota governance (WP-05).

The rule that matters is the failure mode. When a run hits its ceiling it
returns everything it retrieved, marked incomplete, with the reason recorded.
It never truncates silently, and it never lets a model paper over the gap with
a fabricated completion — an answer that *looks* finished but stopped early is
worse than no answer, because nobody knows to check it.

Prices live in ``config/models.yaml`` next to the model ids, because they change
on the same schedule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.config import settings
from qra.models import Organisation, ResearchRun, UsageRecord, User


class BudgetExceeded(RuntimeError):
    """Raised when a call would cross a ceiling. Carries what was spent."""

    def __init__(self, message: str, *, spent: float, ceiling: float):
        super().__init__(message)
        self.spent = spent
        self.ceiling = ceiling


@dataclass
class RunBudget:
    """Tracks one run's spend against its ceiling."""

    run_id: str
    ceiling_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_reason: str | None = None
    entries: list[dict] = field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.ceiling_usd

    def remaining(self) -> float:
        return max(0.0, self.ceiling_usd - self.spent_usd)

    def check(self, estimated_usd: float = 0.0) -> None:
        """Raise before spending, not after."""
        if self.spent_usd + estimated_usd > self.ceiling_usd:
            self.stopped_reason = (
                f"run cost ceiling of ${self.ceiling_usd:.2f} reached after {self.calls} "
                f"model call(s); returning partial results rather than continuing"
            )
            raise BudgetExceeded(
                self.stopped_reason, spent=self.spent_usd, ceiling=self.ceiling_usd
            )

    def record(
        self,
        *,
        provider: str,
        model: str,
        role: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cached: bool = False,
    ) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if not cached:
            self.spent_usd += cost_usd
        self.entries.append(
            {
                "provider": provider,
                "model": model,
                "role": role,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
                "cached": cached,
            }
        )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "ceiling_usd": self.ceiling_usd,
            "spent_usd": round(self.spent_usd, 6),
            "remaining_usd": round(self.remaining(), 6),
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "exhausted": self.exhausted,
            "stopped_reason": self.stopped_reason,
        }


def budget_for(
    session: Session, run_id: str, *, principal=None, ceiling_usd: float | None = None
) -> RunBudget:
    """Build a run budget from the org policy, the user, or the default."""
    ceiling = ceiling_usd
    if ceiling is None and principal is not None and principal.org_id:
        org = session.get(Organisation, principal.org_id)
        ceiling = (org.model_policy or {}).get("run_cost_ceiling_usd") if org else None
    return RunBudget(run_id=run_id, ceiling_usd=ceiling or settings.default_run_cost_ceiling_usd)


def persist(session: Session, budget: RunBudget, *, principal=None) -> None:
    """Write per-call usage rows and roll the total onto the run."""
    for entry in budget.entries:
        session.add(
            UsageRecord(
                run_id=budget.run_id,
                org_id=getattr(principal, "org_id", None),
                user_id=getattr(principal, "user_id", None),
                **entry,
            )
        )
    run = session.get(ResearchRun, budget.run_id)
    if run is not None:
        run.cost_usd = round(budget.spent_usd, 6)
        run.cost_ceiling_usd = budget.ceiling_usd
        if budget.stopped_reason:
            run.incomplete_reason = budget.stopped_reason
    session.commit()


def monthly_usage(session: Session, *, user_id: int | None = None, org_id: int | None = None) -> dict:
    since = datetime.now(UTC) - timedelta(days=30)
    stmt = select(
        func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0),
        func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
        func.count(),
    ).where(UsageRecord.created_at >= since)
    if user_id is not None:
        stmt = stmt.where(UsageRecord.user_id == user_id)
    if org_id is not None:
        stmt = stmt.where(UsageRecord.org_id == org_id)
    tokens, cost, calls = session.execute(stmt).one()
    return {"window_days": 30, "tokens": int(tokens), "cost_usd": round(float(cost), 4), "calls": calls}


def check_monthly_quota(session: Session, principal) -> None:
    """Raise before a run starts if the month's allowance is already gone."""
    if principal is None:
        return
    user = session.get(User, principal.user_id) if principal.user_id else None
    org = session.get(Organisation, principal.org_id) if principal.org_id else None
    budget = (
        (user.monthly_token_budget if user else None)
        or (org.monthly_token_budget if org else None)
        or settings.default_monthly_token_budget
    )
    if not budget:
        return
    used = monthly_usage(
        session, user_id=principal.user_id, org_id=None if user else principal.org_id
    )["tokens"]
    if used >= budget:
        raise BudgetExceeded(
            f"monthly token budget of {budget:,} exhausted ({used:,} used in the last 30 days)",
            spent=used,
            ceiling=budget,
        )
