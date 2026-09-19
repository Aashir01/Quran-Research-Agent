"""The claim registry (Track G).

A Finding is what a run produced. A Claim is an assertion the team stands
behind, and what decays in a research group is not the evidence but the memory
of why a claim was accepted, by whom, and what was said against it.

These tests are almost entirely about refusals, because the registry's value is
in what it will not record.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from qra.models import Claim, ClaimEvent, User
from qra.registry import service
from qra.registry.service import ClaimError
from qra.security.auth import Principal


def _principal(session, email: str, role: str = "researcher") -> Principal:
    from qra.security.service import register_user

    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = register_user(
            session, email=email, password="pw-for-tests-1234", display_name=email.split("@")[0]
        )
        session.commit()
    return Principal(
        user_id=user.id,
        email=user.email,
        role=role,
        org_id=None,
        display_name=user.display_name,
        issuer="test",
    )


@pytest.fixture(autouse=True)
def _leave_no_trace(session):
    high_claim = session.scalar(select(func.max(Claim.id))) or 0
    high_event = session.scalar(select(func.max(ClaimEvent.id))) or 0
    yield
    session.query(ClaimEvent).filter(ClaimEvent.id > high_event).delete(
        synchronize_session=False
    )
    session.query(Claim).filter(Claim.id > high_claim).delete(synchronize_session=False)
    session.commit()


@pytest.fixture
def author(session):
    return _principal(session, "registry-author@example.org")


@pytest.fixture
def reviewer(session):
    return _principal(session, "registry-reviewer@example.org", role="reviewer")


@pytest.fixture
def proposed(session, author):
    return service.propose(
        session,
        author,
        statement="Sabr and salah co-occur beyond chance in Madani surahs",
        evidence_level="L4",
        reason="from the co-occurrence sweep",
    )


# --- what the registry refuses ---------------------------------------------


def test_a_claim_cannot_be_promoted_without_review(session, author, proposed):
    """The point of the registry is that an asserting status has a reviewer
    behind it."""
    with pytest.raises(ClaimError, match="straight from 'proposed'"):
        service.set_status(session, author, proposed["id"], status="supported", reason="looks right")


def test_an_author_cannot_promote_their_own_claim(session, author, reviewer, proposed):
    """Self-approval recorded as review is worse than no status at all."""
    service.set_status(session, reviewer, proposed["id"], status="under_review", reason="picked up")
    with pytest.raises(ClaimError, match="cannot promote it"):
        service.set_status(
            session, author, proposed["id"], status="supported", reason="I checked it myself"
        )


def test_a_reviewer_can_promote_after_review(session, reviewer, proposed):
    service.set_status(session, reviewer, proposed["id"], status="under_review", reason="picked up")
    result = service.set_status(
        session, reviewer, proposed["id"], status="supported", reason="counts and baseline verified"
    )
    assert result["status"] == "supported"


def test_an_explicit_level_needs_a_citation(session, author):
    """L0 and L1 assert what the sources say. Without a citation the level is
    doing work the evidence cannot."""
    for level in ("L0", "L1"):
        with pytest.raises(ClaimError, match="no citation was given"):
            service.propose(
                session,
                author,
                statement=f"The text says X, asserted at {level}",
                evidence_level=level,
                reason="x",
            )


def test_an_inference_level_needs_no_citation(session, author):
    """L4 says 'this is my inference', which is honest without a citation."""
    result = service.propose(
        session, author, statement="An inference with no citation", evidence_level="L4", reason="x"
    )
    assert result["evidence_level"] == "L4"


def test_a_change_without_a_reason_is_refused(session, reviewer, proposed):
    """Six months on, a status with no reason behind it is indistinguishable
    from an accident."""
    with pytest.raises(ClaimError, match="needs a reason"):
        service.set_status(session, reviewer, proposed["id"], status="under_review", reason="  ")


def test_a_claim_cannot_supersede_itself(session, author, proposed):
    with pytest.raises(ClaimError, match="cannot supersede itself"):
        service.supersede(
            session, author, proposed["id"], replacement_id=proposed["id"], reason="x"
        )


def test_a_supersession_cycle_is_refused(session, author, proposed):
    """A claims-superseded-by-B-superseded-by-A chain has no current version,
    and every reader walking it loops."""
    second = service.propose(session, author, statement="A revised version", reason="x")
    service.supersede(
        session, author, proposed["id"], replacement_id=second["id"], reason="revised"
    )
    with pytest.raises(ClaimError, match="cycle"):
        service.supersede(
            session, author, second["id"], replacement_id=proposed["id"], reason="back again"
        )


# --- what it records --------------------------------------------------------


def test_the_status_is_a_projection_of_a_history(session, author, reviewer, proposed):
    service.set_status(session, reviewer, proposed["id"], status="under_review", reason="picked up")
    service.set_status(session, reviewer, proposed["id"], status="supported", reason="verified")

    events = service.history(session, proposed["id"])
    assert [e["kind"] for e in events] == ["proposed", "status_changed", "status_changed"]
    assert [e["to_status"] for e in events] == ["proposed", "under_review", "supported"]
    assert all(e["reason"] for e in events)
    assert all(e["actor"] for e in events)


def test_an_objection_against_an_asserting_claim_contests_it(session, author, reviewer, proposed):
    """Leaving a claim marked 'supported' while an unanswered objection sits
    underneath is the registry telling a reader something it knows to be
    doubtful."""
    service.set_status(session, reviewer, proposed["id"], status="under_review", reason="picked up")
    service.set_status(session, reviewer, proposed["id"], status="supported", reason="verified")

    result = service.raise_objection(
        session,
        author,
        proposed["id"],
        objection="The same pairing holds in the hadith corpus",
        survives_if="the contrast is in degree, which the numbers must show",
    )
    assert result["status"] == "contested"
    assert result["unanswered_objections"] == 1
    assert result["objections"][0]["survives_if"]


def test_an_objection_on_a_proposed_claim_does_not_move_it(session, author, proposed):
    """A claim that asserts nothing yet cannot be contested into doubt."""
    result = service.raise_objection(
        session, author, proposed["id"], objection="worth checking the baseline"
    )
    assert result["status"] == "proposed"
    assert result["unanswered_objections"] == 1


def test_contested_is_a_status_not_an_absence_of_one(session):
    """The classical literature disagrees about most things worth claiming, and
    a schema that could not say so would be made to lie about it."""
    assert "contested" in service.STATUSES
    assert "contested" not in service.ASSERTING


def test_a_superseded_claim_stays_visible(session, author, proposed):
    """A claim once believed and then dropped is what stops the next researcher
    rediscovering it."""
    replacement = service.propose(
        session, author, statement="The corrected version", reason="revised after the control run"
    )
    result = service.supersede(
        session,
        author,
        proposed["id"],
        replacement_id=replacement["id"],
        reason="the hadith control dissolved the contrast",
    )
    assert result["status"] == "withdrawn"
    assert result["superseded_by"] == replacement["id"]
    # Still readable, with the reason attached.
    stored = service.claim(session, proposed["id"])
    assert stored["statement"] == proposed["statement"]
    assert any(e["kind"] == "superseded" for e in stored["history"])


def test_evidence_added_later_is_an_event_too(session, author, proposed):
    result = service.add_evidence(
        session,
        author,
        proposed["id"],
        citations=[{"ref": "2:45", "edition_name": "Qur'an"}],
        reason="found the verse the claim turns on",
    )
    assert len(result["citations"]) == 1
    assert any(e["kind"] == "evidence_added" for e in service.history(session, proposed["id"]))


def test_the_listing_reports_the_spread_of_statuses(session, author, proposed):
    listing = service.listing(session)
    assert listing["total"] >= 1
    assert "proposed" in listing["by_status"]
    assert listing["levels"]["L3"] == "linguistically possible"


# --- the API ---------------------------------------------------------------


def test_the_api_refuses_a_promotion_that_skips_review(session):
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        created = client.post(
            "/claims", json={"statement": "An API claim", "reason": "smoke"}
        ).json()
        response = client.post(
            f"/claims/{created['id']}/status",
            json={"status": "supported", "reason": "skipping review"},
        )
    assert response.status_code == 422
    assert "straight from 'proposed'" in response.json()["detail"]


def test_a_refused_change_leaves_the_claim_untouched(session, reviewer, proposed):
    """The bug this guards: the status was assigned to the in-memory row before
    the reason was validated, so a caught error left a dirty Claim behind — and
    the next commit would persist a status change with no event under it, which
    is exactly what this registry exists to prevent."""
    before = service.claim(session, proposed["id"])["status"]
    with pytest.raises(ClaimError):
        service.set_status(session, reviewer, proposed["id"], status="under_review", reason="")

    # The session must still be usable, and the claim unchanged on both sides.
    session.commit()
    assert service.claim(session, proposed["id"])["status"] == before
    assert session.get(Claim, proposed["id"]).status == before
    assert len(service.history(session, proposed["id"])) == 1
