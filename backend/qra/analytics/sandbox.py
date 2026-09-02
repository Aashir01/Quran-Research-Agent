"""The numerical sandbox, quarantined (WP-33).

One of the interviewed researchers abandoned work on the muqatta'at and their
numerical patterns because it was mostly guesswork. That instinct was correct.
The purpose of this module is to let him go back to it *safely* — not to give
him a faster way to fool himself.

Three things make it a sandbox rather than a calculator:

**The session is the unit, not the test.** Every hypothesis run inside a session
is counted, and the whole family is Benjamini-Hochberg corrected together. You
cannot run forty tests, keep the two that looked striking, and present them as
two tests — the denominator follows the results out of the room.

**Pre-registration is enforced by the schema.** A test's claim and null model are
written before its ``observed`` column is filled. A hypothesis invented after
seeing the count is not a hypothesis, and here it is not even representable.

**The count comes second.** :func:`summary` states how many hypotheses were
tried and how many significant results chance alone predicts *before* any
individual result is shown. That ordering is the acceptance criterion, and it
is the difference between statistics and numerology.

Results are watermarked and cannot leave as findings without reviewer sign-off.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.analytics.stats import ALPHA, Significance, assess, correct_multiple
from qra.models import SandboxSession, SandboxTest


class SandboxError(ValueError):
    """A sandbox rule was broken. Carries which one."""


def open_session(session: Session, *, owner_id: int | None, title: str, intent: str) -> dict:
    """Start a session. ``intent`` is what you say you are looking for, before
    you look — it is quoted back in the summary so a session that wandered is
    visible as one."""
    if not (title or "").strip():
        raise SandboxError("a session needs a title")
    if not (intent or "").strip():
        raise SandboxError(
            "state what you are looking for before you start looking. A session with no "
            "stated intent cannot be told apart later from one that went fishing."
        )
    row = SandboxSession(owner_id=owner_id, title=title.strip(), intent=intent.strip())
    session.add(row)
    session.commit()
    session.refresh(row)
    return to_dict(session, row)


def register(
    session: Session,
    session_id: int,
    *,
    claim: str,
    null_model: str,
    spec: dict | None = None,
) -> dict:
    """Pre-register one counting claim. Nothing is counted yet."""
    row = session.get(SandboxSession, session_id)
    if row is None:
        raise SandboxError(f"sandbox session {session_id} not found")
    if row.closed_at is not None:
        raise SandboxError("this session is closed; open a new one rather than adding to it")
    if not (claim or "").strip():
        raise SandboxError("a test needs a claim")
    if not (null_model or "").strip():
        raise SandboxError(
            "state the null model. 'How often would this happen by chance?' has no answer "
            "until you say what chance means here, and an analytic that cannot name its "
            "null model has no business reporting a finding."
        )
    test = SandboxTest(
        session_id=session_id,
        claim=claim.strip(),
        null_model=null_model.strip(),
        spec=spec or {},
    )
    session.add(test)
    session.commit()
    session.refresh(test)
    return test_to_dict(test)


def run(
    session: Session,
    test_id: int,
    *,
    observed: int,
    n: int,
    baseline_rate: float,
) -> dict:
    """Run a pre-registered test.

    The caller supplies the count and the baseline; this module's job is to
    refuse to let the result be read in isolation. The returned payload always
    carries the session-wide correction, never the bare p-value.
    """
    test = session.get(SandboxTest, test_id)
    if test is None:
        raise SandboxError(f"test {test_id} not found")
    if test.ran_at is not None:
        raise SandboxError(
            "this test has already run. Re-running the same claim until it comes out "
            "significant is the failure this sandbox exists to prevent."
        )
    if not 0 < baseline_rate < 1:
        raise SandboxError("baseline_rate must be a probability strictly between 0 and 1")

    result = assess(observed, n, baseline_rate, label=test.claim[:80])
    test.observed = observed
    test.expected = result.expected
    test.p_value = result.p_value
    test.ran_at = datetime.now(UTC)

    parent = session.get(SandboxSession, test.session_id)
    parent.tests_run = (
        session.scalar(
            select(func.count())
            .select_from(SandboxTest)
            .where(SandboxTest.session_id == parent.id, SandboxTest.ran_at.is_not(None))
        )
        or 0
    )
    session.commit()

    # Correct the whole family, every time. A result computed in isolation is
    # the thing this module refuses to produce.
    _recorrect(session, parent.id)
    session.refresh(test)
    return {
        "test": test_to_dict(test),
        "session": summary(session, parent.id),
        "watermark": WATERMARK,
    }


def _recorrect(session: Session, session_id: int) -> None:
    """Re-run Benjamini-Hochberg across every test in the session.

    Called after each run, because adding a forty-first test changes the verdict
    on the previous forty. Storing an uncorrected p as if it were final would be
    the same error in slower motion.
    """
    tests = session.scalars(
        select(SandboxTest).where(
            SandboxTest.session_id == session_id, SandboxTest.ran_at.is_not(None)
        )
    ).all()
    if not tests:
        return
    family = [
        Significance(
            observed=t.observed or 0,
            expected=t.expected or 0.0,
            n=0,
            p_value=t.p_value or 1.0,
            effect_size=0.0,
            effect_measure="",
            test="binomial",
            within_chance=True,
            direction="",
            interpretation="",
        )
        for t in tests
    ]
    corrected = correct_multiple(family)
    for test, result in zip(tests, corrected, strict=True):
        test.corrected_p = result.corrected_p
        test.within_chance = result.within_chance
    session.commit()


WATERMARK = (
    "SANDBOX RESULT — exploratory. Corrected for every hypothesis tested in this "
    "session. Not exportable as a finding without reviewer sign-off."
)


def summary(session: Session, session_id: int) -> dict:
    """The session, with the honesty stated before any individual result.

    The ordering of this payload is the product rule: ``headline`` comes before
    ``tests``, and it names how many hypotheses were tried and how many
    significant results chance alone predicts.
    """
    row = session.get(SandboxSession, session_id)
    if row is None:
        raise SandboxError(f"sandbox session {session_id} not found")

    tests = session.scalars(
        select(SandboxTest).where(SandboxTest.session_id == session_id).order_by(SandboxTest.id)
    ).all()
    ran = [t for t in tests if t.ran_at is not None]
    survived = [t for t in ran if t.within_chance is False]
    naive = [t for t in ran if (t.p_value or 1.0) < ALPHA]
    expected_by_chance = len(ran) * ALPHA

    return {
        "id": row.id,
        "title": row.title,
        "intent": row.intent,
        # Stated first, always, before any result.
        "headline": (
            f"You tested {len(ran)} hypothes{'is' if len(ran) == 1 else 'es'}; "
            f"{expected_by_chance:.1f} significant result"
            f"{'' if abs(expected_by_chance - 1) < 0.05 else 's'} "
            f"{'is' if abs(expected_by_chance - 1) < 0.05 else 'are'} expected by chance alone."
        ),
        "tests_registered": len(tests),
        "tests_run": len(ran),
        "significant_before_correction": len(naive),
        "significant_after_correction": len(survived),
        "expected_by_chance": round(expected_by_chance, 2),
        "alpha": ALPHA,
        "correction": "benjamini_hochberg over every test in this session",
        "watermark": WATERMARK,
        "reading": (
            f"{len(naive)} of {len(ran)} looked significant on their own, which is close to the "
            f"{expected_by_chance:.1f} chance predicts. {len(survived)} survive correction."
            if len(ran)
            else "Nothing has been run yet."
        ),
        "tests": [test_to_dict(t) for t in tests],
        "closed": row.closed_at is not None,
    }


def close(session: Session, session_id: int) -> dict:
    """Close a session. The count of what was tried is now permanent."""
    row = session.get(SandboxSession, session_id)
    if row is None:
        raise SandboxError(f"sandbox session {session_id} not found")
    row.closed_at = datetime.now(UTC)
    session.commit()
    return summary(session, session_id)


def to_dict(session: Session, row: SandboxSession) -> dict:
    return summary(session, row.id)


def test_to_dict(test: SandboxTest) -> dict:
    return {
        "id": test.id,
        "claim": test.claim,
        "null_model": test.null_model,
        "registered_at": test.registered_at.isoformat(),
        "ran": test.ran_at is not None,
        "observed": test.observed,
        "expected": round(test.expected, 2) if test.expected is not None else None,
        "p_value": test.p_value,
        "corrected_p": test.corrected_p,
        # Uncorrected significance is deliberately not surfaced as a verdict.
        "verdict": (
            None
            if test.ran_at is None
            else ("within chance" if test.within_chance else "beyond chance after correction")
        ),
    }
