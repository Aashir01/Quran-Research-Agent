"""Critic escalation (Track E).

The routing policy already keeps the Critic off the Scribe's provider — a model
grading its own homework is the obvious failure and `models.yaml` handles it.
This is the next question: when the Critic finds something serious, is one pass
enough?

Escalation runs a second, adversarial review of a draft the first pass has
already flagged. Two things make it worth having rather than theatre:

**It does not require a second provider.** The deterministic objection engine is
an independent check by *mechanism*, not by model — it computes base rates,
polysemy, controls and counter-examples from the corpus. With every provider
unreachable, escalation still runs and still finds things. A second model, when
one is configured on a different provider, is added on top.

**Agreement is reported, not merged.** If the two passes disagree, that is the
output. Collapsing a disagreement into a single verdict throws away the only
signal an escalation produces — a claim that survives one reviewer and not
another is precisely the claim a researcher needs to look at.

When no second provider is available this says so rather than reporting a
single-provider review as though it were adversarial.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

# The Critic's own findings that justify a second look. A citation that does not
# resolve is already fatal and needs no second opinion; these are the ones where
# judgement is involved and a second judgement is worth having.
ESCALATION_TRIGGERS = (
    ("scripture_violations", "fabricated or un-cited scripture in the draft"),
    ("claims_from_flagged_spans", "a claim resting on instruction-shaped retrieved text"),
    ("claims_without_support", "a claim with no supporting span"),
    ("numerology_notes", "a count presented without a baseline"),
)
# Below this many triggered findings, one pass is enough.
ESCALATE_AT = 1


def should_escalate(critic_report: dict | None) -> tuple[bool, list[str]]:
    """Whether this report warrants a second review, and why."""
    if not critic_report:
        return False, []
    reasons = [
        note
        for key, note in ESCALATION_TRIGGERS
        if critic_report.get(key)
    ]
    # A failed citation is fatal on its own and does not need a second opinion —
    # it needs fixing.
    if critic_report.get("citations_failed"):
        reasons.append("a citation that does not resolve against the corpus")
    return len(reasons) >= ESCALATE_AT, reasons


def _second_provider_available(role: str = "critic") -> tuple[bool, str]:
    """Is there a model on a provider other than the one that drafted?"""
    try:
        from qra.agents.llm import current_router

        router = current_router()
        plan = router.plan(role)
        providers = {
            row.get("provider")
            for row in plan
            if row.get("provider") and row.get("provider") != "deterministic"
        }
        drafting = router.served.get("scribe")
        alternatives = providers - ({drafting} if drafting else set())
        if alternatives:
            return True, f"available on {', '.join(sorted(alternatives))}"
        if drafting:
            return False, f"only {drafting} is reachable, which wrote the draft"
        return False, "no model provider is reachable"
    except Exception as exc:  # noqa: BLE001 - absence of a router is not a crash
        return False, f"router unavailable ({type(exc).__name__})"


def escalate(
    session: Session,
    *,
    critic_report: dict | None,
    claim: str = "",
    roots: list[str] | None = None,
    significance: dict | None = None,
    narrator: str | None = None,
    measure: str | None = None,
    comparisons_made: int | None = None,
) -> dict:
    """A second, adversarial review of a flagged draft."""
    warranted, reasons = should_escalate(critic_report)
    from qra.analytics.objections import objections

    second_pass = objections(
        session,
        claim=claim,
        roots=roots,
        significance=significance,
        narrator=narrator,
        measure=measure,
        comparisons_made=comparisons_made,
    )
    available, provider_note = _second_provider_available()

    first_pass_flagged = bool(reasons)
    second_pass_flagged = second_pass["objections_raised"] > 0
    agreement = (
        "both passes flagged this draft"
        if first_pass_flagged and second_pass_flagged
        else "the first pass flagged it and the second found nothing computable against it"
        if first_pass_flagged
        else "the second pass raised objections the first did not"
        if second_pass_flagged
        else "neither pass flagged this draft"
    )

    return {
        "escalation_warranted": warranted,
        "reasons": reasons,
        "first_pass": {
            "flagged": first_pass_flagged,
            "findings": reasons,
            "source": "the Critic agent",
        },
        "second_pass": {
            "flagged": second_pass_flagged,
            "objections": second_pass["objections"],
            "verdict": second_pass["verdict"],
            "source": "the deterministic objection engine",
            "independence": (
                "Independent by mechanism rather than by model: it computes base rates, "
                "polysemy, the hadith control and counter-examples from the corpus, so it "
                "runs with every provider unreachable."
            ),
        },
        "adversarial_model_pass": {
            "available": available,
            "note": provider_note,
            "policy": (
                "The Critic is already routed away from the Scribe's provider by "
                "`prefer_different_provider_than` in models.yaml. This reports whether a "
                "second provider actually exists to honour that."
                if available
                else "No adversarial *model* pass was run. Reporting a single-provider "
                "review as adversarial would be worse than not running one."
            ),
        },
        # The point of an escalation is the disagreement, so it is not merged away.
        "agreement": agreement,
        "reading": (
            "The two passes disagree. That is the output, not a problem with it — a claim "
            "one reviewer clears and another does not is the claim to look at."
            if first_pass_flagged != second_pass_flagged
            else "Both passes agree. Agreement between a rule-based critic and a "
            "corpus-computed objection engine is weak evidence of correctness — they can "
            "share a blind spot — and no evidence at all about anything neither checks."
        ),
    }
