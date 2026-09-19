"""Organisation isolation (Track G).

Not a feature — a bug that was live. `review_queue` and `search_prior_work`
both listed `Finding` rows with no organisation filter, and neither function
took a principal, so it could not have filtered even if a caller had wanted it
to. A reviewer in one organisation saw another's unpublished drafts, and the
Librarian's prior-work search surfaced a different team's research.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from qra.models import Finding, Organisation
from qra.security.auth import Principal
from qra.workspace import service

PROBE = "tenancy-probe"


def _org(session, name: str) -> Organisation:
    row = session.scalar(select(Organisation).where(Organisation.name == name))
    if row is None:
        row = Organisation(name=name, slug=name.lower().replace(" ", "-"))
        session.add(row)
        session.flush()
    return row


@pytest.fixture
def two_orgs(session):
    alpha, beta = _org(session, "Tenancy Alpha"), _org(session, "Tenancy Beta")
    session.add_all(
        [
            Finding(
                question="Beta's confidential research on sabr",
                summary="private to beta",
                org_id=beta.id,
                fingerprint=PROBE,
                review_status="submitted",
            ),
            Finding(
                question="Alpha's own research on sabr",
                summary="private to alpha",
                org_id=alpha.id,
                fingerprint=PROBE,
                review_status="submitted",
            ),
            Finding(
                question="An unowned finding about sabr",
                summary="no organisation",
                org_id=None,
                fingerprint=PROBE,
                review_status="submitted",
            ),
        ]
    )
    session.commit()
    yield alpha, beta
    session.query(Finding).filter(Finding.fingerprint == PROBE).delete(
        synchronize_session=False
    )
    session.commit()


def _principal(org_id: int | None) -> Principal:
    return Principal(
        user_id=1, email="x@example.org", role="reviewer", org_id=org_id, display_name="x"
    )


def test_the_review_queue_does_not_leak_across_organisations(session, two_orgs):
    alpha, beta = two_orgs
    queue = service.review_queue(session, principal=_principal(alpha.id))
    questions = {row["question"] for row in queue}
    assert "Alpha's own research on sabr" in questions
    assert "Beta's confidential research on sabr" not in questions


def test_prior_work_does_not_leak_across_organisations(session, two_orgs):
    """The point is to surface *your team's* prior work. Surfacing another
    team's is a leak rather than a feature."""
    alpha, beta = two_orgs
    found = service.search_prior_work(
        session, "research about sabr", principal=_principal(beta.id)
    )
    questions = {row["question"] for row in found}
    assert "Beta's confidential research on sabr" in questions
    assert "Alpha's own research on sabr" not in questions


def test_a_principal_with_no_organisation_sees_only_unowned_rows(session, two_orgs):
    """The strict reading, deliberately: `org_id IS NULL` meaning "everyone's"
    is how this kind of filter silently stops filtering."""
    queue = service.review_queue(session, principal=_principal(None))
    questions = {row["question"] for row in queue}
    assert "An unowned finding about sabr" in questions
    assert "Alpha's own research on sabr" not in questions
    assert "Beta's confidential research on sabr" not in questions


def test_both_listings_take_a_principal(session):
    """They did not, which is why they could not filter. A signature that
    cannot express the constraint cannot enforce it."""
    import inspect

    for fn in (service.review_queue, service.search_prior_work):
        assert "principal" in inspect.signature(fn).parameters, fn.__name__


def test_the_api_scopes_the_review_queue(session, two_orgs):
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        response = client.get("/research/review-queue")
    assert response.status_code == 200
    # Auth is disabled in this deployment, so the local principal has no
    # organisation and must therefore see only unowned rows.
    questions = {row["question"] for row in response.json()}
    assert "Beta's confidential research on sabr" not in questions
    assert "Alpha's own research on sabr" not in questions
