"""Shared API dependencies.

``principal`` is the single place a route learns who is calling. When auth is
disabled it returns a clearly-labelled local admin rather than ``None``, so no
route has to branch on the deployment mode — and ``/meta/capabilities`` reports
which mode is live so an open deployment cannot be mistaken for a secured one.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from qra.security.auth import (
    Principal,
    RoleError,
    auth_enabled,
    bootstrap_principal,
    current_principal,
)


def principal_or_local(request: Request) -> Principal:
    found = current_principal(request)
    if found is not None:
        return found
    if auth_enabled():
        raise HTTPException(401, "authentication required")
    return bootstrap_principal()


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
