"""WP-01: identity, roles and row-level ownership.

The acceptance criteria are specific: an unauthenticated workspace call is 401,
and a researcher cannot approve their own finding. Both are asserted here, plus
the ownership rules that make the first one meaningful.
"""

import pytest
from fastapi.testclient import TestClient

from qra.api.main import app
from qra.config import settings
from qra.security.auth import (
    Principal,
    RoleError,
    TokenError,
    hash_password,
    issue_token,
    verify_password,
    verify_token,
)


@pytest.fixture
def secured(monkeypatch):
    """Turn auth on for the duration of a test."""
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-for-suite")
    return settings


def test_role_ordering_is_a_hierarchy():
    reviewer = Principal(user_id=1, email="r@x", role="reviewer")
    assert reviewer.has_role("reader") and reviewer.has_role("researcher")
    assert not reviewer.has_role("admin")
    with pytest.raises(RoleError):
        reviewer.require("admin")


def test_passwords_are_salted_and_verified_in_constant_time():
    first, second = hash_password("same"), hash_password("same")
    assert first != second  # per-user salt
    assert verify_password("same", first)
    assert not verify_password("Same", first)
    assert not verify_password("anything", None)


def test_token_roundtrip_and_tamper_detection(secured):
    principal = Principal(user_id=7, email="a@b", role="reviewer", org_id=3)
    token = issue_token(principal)
    restored = verify_token(token)
    assert (restored.user_id, restored.role, restored.org_id) == (7, "reviewer", 3)

    header, body, signature = token.split(".")
    with pytest.raises(TokenError):
        verify_token(f"{header}.{body}.{'a' * len(signature)}")


def test_expired_token_is_rejected(secured):
    token = issue_token(Principal(user_id=1, email="a@b"), ttl_seconds=-1)
    with pytest.raises(TokenError):
        verify_token(token)


def test_unauthenticated_workspace_call_is_401(secured):
    client = TestClient(app)
    assert client.get("/workspace/notes").status_code == 401
    assert client.post("/workspace/notes", json={"title": "x", "body": "y"}).status_code == 401


def test_reader_cannot_write(secured):
    token = issue_token(Principal(user_id=2, email="reader@x", role="reader"))
    client = TestClient(app)
    response = client.post(
        "/workspace/notes",
        json={"title": "x", "body": "y"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_ownership_rules(secured):
    class Row:
        author_id = 5
        org_id = 1
        visibility = "private"

    owner = Principal(user_id=5, email="o@x", org_id=1)
    stranger = Principal(user_id=6, email="s@x", org_id=1)
    admin = Principal(user_id=9, email="a@x", role="admin", org_id=1)
    other_org_admin = Principal(user_id=10, email="a2@x", role="admin", org_id=2)

    assert owner.owns(Row())
    assert not stranger.owns(Row())
    assert admin.owns(Row())  # same org
    assert not other_org_admin.owns(Row())


@pytest.fixture
def two_users(session):
    """An author and a separate reviewer, as real rows — the FK is part of the rule."""
    import uuid

    from qra.security.service import register_user

    tag = uuid.uuid4().hex[:8]
    author = register_user(session, email=f"author-{tag}@x", password="pw", role="researcher")
    reviewer = register_user(session, email=f"reviewer-{tag}@x", password="pw", role="reviewer")
    return author, reviewer


def test_a_researcher_cannot_approve_their_own_finding(session, two_users):
    from qra.models import Finding
    from qra.workspace.service import review_finding

    author, reviewer = two_users
    finding = Finding(
        author_id=author.id, question="q", summary="s", fingerprint="fp", review_status="submitted"
    )
    session.add(finding)
    session.commit()

    with pytest.raises(ValueError, match="own author"):
        review_finding(session, finding.id, reviewer_id=author.id, approve=True)

    payload = review_finding(session, finding.id, reviewer_id=reviewer.id, approve=True)
    assert payload["review_status"] == "approved"


def test_review_requires_the_reviewer_role(session, two_users):
    from qra.models import Finding
    from qra.workspace.service import review_finding

    author, _ = two_users
    finding = Finding(author_id=author.id, question="q", summary="s", fingerprint="fp2")
    session.add(finding)
    session.commit()
    researcher = Principal(user_id=author.id, email=author.email, role="researcher")
    with pytest.raises(RoleError):
        review_finding(
            session, finding.id, reviewer_id=author.id, approve=True, principal=researcher
        )


def test_auth_disabled_yields_a_labelled_local_admin(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", None)
    client = TestClient(app)
    payload = client.get("/auth/me").json()
    assert payload["auth_enabled"] is False
    assert payload["role"] == "admin"
    assert "auth disabled" in payload["display_name"]


def test_the_openapi_schema_can_be_built():
    """A regression that took out the whole schema, silently.

    ``require_role`` imports ``Request`` inside the factory, and the module uses
    ``from __future__ import annotations`` — so the parameter annotation was the
    string "Request" with nothing able to resolve it. FastAPI tolerated that at
    call time, so every route worked and every test passed; Pydantic could not
    build a schema from it, so ``/openapi.json`` returned 500 and took ``/docs``
    and every generated client with it.

    Nothing else in the suite touches the schema, which is exactly why this is
    here.
    """
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200, response.text[:400]
    paths = response.json()["paths"]
    # Every router is represented, so a future forward-ref break is caught
    # wherever it happens rather than only in the security module.
    assert len(paths) > 100
    for prefix in ("/analysis", "/grammar", "/community", "/auth", "/corpus"):
        assert any(path.startswith(prefix) for path in paths), prefix
