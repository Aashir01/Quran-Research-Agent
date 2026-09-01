"""Shared API dependencies.

``principal`` is the single place a route learns who is calling. When auth is
disabled it returns a clearly-labelled local admin rather than ``None``, so no
route has to branch on the deployment mode — and ``/meta/capabilities`` reports
which mode is live so an open deployment cannot be mistaken for a secured one.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from qra.db import session_scope
from qra.security.auth import (
    Principal,
    RoleError,
    auth_enabled,
    current_principal,
)


def principal_or_local(request: Request) -> Principal:
    found = current_principal(request)
    if found is not None:
        return found
    if auth_enabled():
        raise HTTPException(401, "authentication required")
    # Auth is off. The bootstrap identity is resolved to a *real* user row here
    # rather than left as a sentinel id, because every authored write in the app
    # — notes, findings, posts — carries a foreign key to app_user. Doing it in
    # this one place means no route has to remember.
    from qra.security.service import local_user

    with session_scope() as session:
        row = local_user(session)
        user_id, display_name = row.id, row.display_name
    return Principal(
        user_id=user_id,
        email="local@localhost",
        role="admin",
        org_id=None,
        display_name=display_name,
        issuer="disabled",
    )


def needs(role: str):
    """Require a role, honouring the auth-disabled bootstrap principal."""

    def dependency(principal: Principal = Depends(principal_or_local)) -> Principal:
        try:
            principal.require(role)
        except RoleError as exc:
            raise HTTPException(403, str(exc)) from exc
        return principal

    return Depends(dependency)


CurrentUser = Depends(principal_or_local)
