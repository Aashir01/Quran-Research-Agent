"""Authentication and authorisation.

The team layer previously took ``author_id`` from the caller, which is a hole
rather than a feature: any client could claim to be any researcher, and the
reviewer separation was advisory. This module makes identity something the
server establishes.

Two paths, deliberately:

* **OIDC** for institutions that already have an identity provider. We verify
  the token's signature against the provider's JWKS and map the subject to a
  local user.
* **Local password** for a single-team deployment that does not want to run an
  IdP. PBKDF2-SHA256 with a per-user salt; no third-party dependency.

Roles are ordered — ``reader < researcher < reviewer < admin`` — and checked
against that order, so a route that needs ``researcher`` also accepts an admin
without every route enumerating the ranks above it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from qra.config import settings

ROLES = ("reader", "researcher", "reviewer", "admin")
_RANK = {role: index for index, role in enumerate(ROLES)}

# PBKDF2 cost. Raise with hardware; the stored hash records the value used so
# existing passwords keep verifying after a change.
_PBKDF2_ROUNDS = 240_000


class RoleError(PermissionError):
    """Raised when a principal lacks the required role."""


class TokenError(ValueError):
    """Raised for a malformed, expired or badly-signed token."""


@dataclass(frozen=True)
class Principal:
    """Who is making this request. Never constructed from client-supplied ids."""

    user_id: int
    email: str
    role: str = "researcher"
    org_id: int | None = None
    display_name: str = ""
    # Where the identity came from, so an audit trail can distinguish a local
    # login from a federated one.
    issuer: str = "local"

    def has_role(self, required: str) -> bool:
        return _RANK.get(self.role, -1) >= _RANK.get(required, 99)

    def require(self, required: str) -> None:
        if not self.has_role(required):
            raise RoleError(f"role '{required}' required; principal has '{self.role}'")

    def owns(self, row) -> bool:
        """Row-level ownership, with admins able to see their own org's rows."""
        author = getattr(row, "author_id", None) or getattr(row, "owner_id", None)
        if author is not None and author == self.user_id:
            return True
        if self.has_role("admin") and getattr(row, "org_id", None) == self.org_id:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "role": self.role,
            "org_id": self.org_id,
            "display_name": self.display_name,
            "issuer": self.issuer,
        }


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, rounds, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = base64.b64decode(digest_b64)
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(salt_b64), int(rounds)
    )
    # Constant time: a timing side channel here leaks password prefixes.
    return hmac.compare_digest(expected, actual)


# ---------------------------------------------------------------------------
# Tokens — HS256 JWT, self-issued
# ---------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    secret = settings.jwt_secret
    if not secret:
        raise TokenError(
            "QRA_JWT_SECRET is not set. Auth cannot be enabled without it; "
            "generate one with `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`."
        )
    return secret.encode()


def issue_token(principal: Principal, *, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds or settings.jwt_ttl_seconds
    now = int(time.time())
    payload = {
        **principal.to_dict(),
        "sub": str(principal.user_id),
        "iat": now,
        "exp": now + ttl,
    }
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64url(hmac.new(_secret(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def verify_token(token: str) -> Principal:
    try:
        header, body, signature = token.split(".")
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    expected = _b64url(hmac.new(_secret(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise TokenError("bad signature")
    payload = json.loads(_unb64url(body))
    if payload.get("exp", 0) < time.time():
        raise TokenError("token expired")
    return Principal(
        user_id=int(payload["user_id"]),
        email=payload.get("email", ""),
        role=payload.get("role", "reader"),
        org_id=payload.get("org_id"),
        display_name=payload.get("display_name", ""),
        issuer=payload.get("issuer", "local"),
    )


# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------


def verify_oidc_token(token: str) -> dict:
    """Verify an external OIDC id token against the provider's JWKS.

    Kept deliberately small: we validate signature, issuer, audience and expiry,
    and hand back claims. Mapping claims to a local user is the caller's job,
    because that mapping is a deployment policy question.
    """
    if not settings.oidc_issuer:
        raise TokenError("OIDC is not configured (QRA_OIDC_ISSUER unset)")
    try:
        import httpx
        from jwt import PyJWKClient, decode  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional extra
        raise TokenError(
            "OIDC verification needs the `auth` extra: pip install 'qra[auth]'"
        ) from exc

    with httpx.Client(timeout=10.0) as client:
        config = client.get(
            f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        ).json()
    signing_key = PyJWKClient(config["jwks_uri"]).get_signing_key_from_jwt(token)
    return decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.oidc_audience,
        issuer=config["issuer"],
    )


# ---------------------------------------------------------------------------
# FastAPI plumbing
# ---------------------------------------------------------------------------


def require_role(required: str = "researcher"):
    """Dependency factory: 401 without a valid token, 403 without the role."""
    from fastapi import Depends, HTTPException, Request

    # This module uses `from __future__ import annotations`, so `request:
    # Request` below is stored as the *string* "Request" — and `Request` is a
    # local of this factory, not a module global, so nothing can resolve it.
    # FastAPI tolerates that at call time but Pydantic cannot build a schema
    # from it, which took out /openapi.json (and with it /docs and every
    # generated client) for the whole application. Binding the annotation to
    # the real class keeps the import lazy and the schema buildable.
    def dependency(request) -> Principal:
        principal = current_principal(request)
        if principal is None:
            raise HTTPException(401, "authentication required")
        try:
            principal.require(required)
        except RoleError as exc:
            raise HTTPException(403, str(exc)) from exc
        return principal

    dependency.__annotations__["request"] = Request
    return Depends(dependency)


def current_principal(request) -> Principal | None:
    """Read the principal from the Authorization header, or None."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        return verify_token(header.split(" ", 1)[1].strip())
    except TokenError:
        return None


def auth_enabled() -> bool:
    """Auth is on when a secret is configured.

    A deployment without QRA_JWT_SECRET runs open, which is fine for a laptop
    and never fine for a shared server — /meta/capabilities reports which mode
    is live so it cannot be mistaken.
    """
    return bool(settings.jwt_secret)


def bootstrap_principal() -> Principal:
    """The identity used when auth is disabled: a clearly-labelled local admin.

    ``user_id`` is 0, which is a sentinel and not a row in ``app_user``. Anything
    that *writes* an authored record must go through
    :func:`qra.api.deps.principal_or_local`, which resolves this to the real
    persisted local account — a foreign key does not care that a deployment is
    running open.
    """
    return Principal(
        user_id=0,
        email="local@localhost",
        role="admin",
        org_id=None,
        display_name="local (auth disabled)",
        issuer="disabled",
    )
