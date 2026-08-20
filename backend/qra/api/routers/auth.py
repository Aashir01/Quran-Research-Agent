"""Authentication endpoints (WP-01)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from qra.db import get_session
from qra.security import auth as auth_mod
from qra.security import service as identity

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(
    email: str = Body(...),
    password: str = Body(...),
    display_name: str | None = Body(None),
    session: Session = Depends(get_session),
) -> dict:
    """Create a user. The first user on a fresh deployment becomes admin."""
    try:
        user = identity.register_user(
            session, email=email, password=password, display_name=display_name
        )
    except identity.AuthError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": user.id, "email": user.email, "role": user.role}


@router.post("/token")
def token(
    email: str = Body(...), password: str = Body(...), session: Session = Depends(get_session)
) -> dict:
    try:
        return {"access_token": identity.authenticate(session, email=email, password=password),
                "token_type": "bearer"}
    except identity.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    except auth_mod.TokenError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/oidc")
def oidc(id_token: str = Body(..., embed=True), session: Session = Depends(get_session)) -> dict:
    """Exchange a verified OIDC id token for a local session token."""
    try:
        claims = auth_mod.verify_oidc_token(id_token)
        principal = identity.principal_from_oidc(session, claims)
    except (auth_mod.TokenError, identity.AuthError) as exc:
        raise HTTPException(401, str(exc)) from exc
    return {"access_token": auth_mod.issue_token(principal), "token_type": "bearer"}


@router.get("/me")
def me(request: Request) -> dict:
    principal = auth_mod.current_principal(request)
    if principal is None:
        if not auth_mod.auth_enabled():
            return {**auth_mod.bootstrap_principal().to_dict(), "auth_enabled": False}
        raise HTTPException(401, "authentication required")
    return {**principal.to_dict(), "auth_enabled": True}


@router.post("/users/{user_id}/role")
def set_role(
    user_id: int,
    role: str = Body(..., embed=True),
    principal=auth_mod.require_role("admin"),
    session: Session = Depends(get_session),
) -> dict:
    try:
        user = identity.set_role(session, principal, user_id=user_id, role=role)
    except identity.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": user.id, "role": user.role}


@router.post("/keys")
def store_key(
    provider: str = Body(...),
    key: str = Body(...),
    org_wide: bool = Body(False),
    principal=auth_mod.require_role("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Store a provider key. The response carries a fingerprint, never the key."""
    return identity.store_provider_key(
        session, principal, provider=provider, key=key, org_wide=org_wide
    )


@router.get("/keys")
def list_keys(
    principal=auth_mod.require_role("researcher"), session: Session = Depends(get_session)
) -> list[dict]:
    return identity.list_provider_keys(session, principal)


@router.post("/orgs")
def create_org(
    slug: str = Body(...),
    name: str = Body(...),
    privacy_mode: str = Body("standard"),
    principal=auth_mod.require_role("admin"),
    session: Session = Depends(get_session),
) -> dict:
    """Create a tenant. `local_only` refuses every hosted provider call."""
    try:
        org = identity.create_org(session, slug=slug, name=name, privacy_mode=privacy_mode)
    except identity.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": org.id, "slug": org.slug, "privacy_mode": org.privacy_mode}
