"""The public portal (Track G).

The most damaging surface in the application, because it is the one that gets
screenshotted. Every test here is about what it refuses to show, or about what
it refuses to show *without*.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from qra.api.main import app
from qra.api.routers.portal import PUBLIC_CLAIM_STATUSES
from qra.models import Claim, ClaimEvent, User
from qra.registry import service
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
        user_id=user.id, email=user.email, role=role, org_id=None,
        display_name=user.display_name, issuer="test",
    )


@pytest.fixture
def published(session):
    """One claim of each interesting kind: published, proposed, superseded."""
    high_claim = session.scalar(select(func.max(Claim.id))) or 0
    high_event = session.scalar(select(func.max(ClaimEvent.id))) or 0

    author = _principal(session, "portal-author@example.org")
    reviewer = _principal(session, "portal-reviewer@example.org", role="reviewer")

    live = service.propose(
        session, author, statement="A published claim about sabr", evidence_level="L3",
        reason="from the sweep",
    )
    service.set_status(session, reviewer, live["id"], status="under_review", reason="picked up")
    live = service.set_status(
        session, reviewer, live["id"], status="supported", reason="baseline verified"
    )
    draft = service.propose(
        session, author, statement="An unreviewed proposal about sabr", reason="draft"
    )
    old = service.propose(session, author, statement="A superseded claim", reason="old")
    service.supersede(
        session, author, old["id"], replacement_id=live["id"], reason="replaced by the reviewed one"
    )

    yield {"live": live, "draft": draft, "superseded": old, "author": author}

    session.query(ClaimEvent).filter(ClaimEvent.id > high_event).delete(synchronize_session=False)
    session.query(Claim).filter(Claim.id > high_claim).delete(synchronize_session=False)
    session.commit()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_an_unreviewed_claim_is_never_published(client, published):
    statements = {c["statement"] for c in client.get("/portal/claims").json()["claims"]}
    assert published["live"]["statement"] in statements
    assert published["draft"]["statement"] not in statements


def test_a_superseded_claim_is_not_published(client, published):
    """It stays readable internally with its reason. It is not a current result."""
    statements = {c["statement"] for c in client.get("/portal/claims").json()["claims"]}
    assert published["superseded"]["statement"] not in statements


def test_an_unpublished_claim_is_indistinguishable_from_a_missing_one(client, published):
    """Confirming that an unpublished claim exists is itself a disclosure."""
    response = client.get(f"/portal/claims/{published['draft']['slug']}")
    assert response.status_code == 404
    assert client.get("/portal/claims/a-claim-that-does-not-exist").status_code == 404


def test_a_published_claim_carries_its_evidence_level(client, published):
    """L3 means the Arabic can bear this reading among others. Publishing the
    conclusion without the level is the failure this portal exists to avoid."""
    payload = client.get(f"/portal/claims/{published['live']['slug']}").json()
    assert payload["evidence_level"] == "L3"
    assert payload["evidence_level_meaning"] == "linguistically possible"


def test_objections_are_published_beside_the_claim(client, session, published):
    """Behind a login they would be invisible exactly where they matter most."""
    author = published["author"]
    service.raise_objection(
        session,
        author,
        published["live"]["id"],
        objection="the same pairing holds in the hadith corpus",
        survives_if="the contrast is in degree",
    )
    payload = client.get(f"/portal/claims/{published['live']['slug']}").json()
    assert payload["unanswered_objections"] == 1
    assert payload["objections"][0]["survives_if"]


def test_a_contested_claim_is_shown_as_contested_not_withheld(client, session, published):
    """Withholding it would let the portal read as a list of settled results,
    which is the impression this material least supports."""
    service.raise_objection(
        session, published["author"], published["live"]["id"], objection="an objection"
    )
    listed = client.get("/portal/claims").json()["claims"]
    row = next(c for c in listed if c["slug"] == published["live"]["slug"])
    assert row["status"] == "contested"
    assert "contested" in PUBLIC_CLAIM_STATUSES


def test_a_non_public_status_cannot_be_requested(client):
    """The filter is a whitelist, so asking for drafts is a 404 rather than an
    empty list that might later become non-empty."""
    assert client.get("/portal/claims", params={"status": "proposed"}).status_code == 404
    assert client.get("/portal/claims", params={"status": "withdrawn"}).status_code == 404


def test_only_approved_findings_are_published(client, session):
    from qra.models import Finding

    probe = "portal-probe"
    session.add_all(
        [
            Finding(question="an approved finding", summary="s", review_status="approved",
                    fingerprint=probe),
            Finding(question="a submitted finding", summary="s", review_status="submitted",
                    fingerprint=probe),
        ]
    )
    session.commit()
    try:
        questions = {f["question"] for f in client.get("/portal/findings").json()["findings"]}
        assert "an approved finding" in questions
        assert "a submitted finding" not in questions
    finally:
        session.query(Finding).filter(Finding.fingerprint == probe).delete(
            synchronize_session=False
        )
        session.commit()


def test_the_index_says_what_it_does_not_show(client):
    payload = client.get("/portal").json()
    assert "never selected rather than filtered out" in payload["what_is_not_here"]
    assert "evidence level" in payload["caveat"]


def test_the_portal_needs_no_authentication(client, published):
    """It is a read-only public surface. If it needed a login it would not be a
    portal — and every route here must stay safe without one."""
    for path in ("/portal", "/portal/claims", "/portal/findings"):
        assert client.get(path, headers={}).status_code == 200
