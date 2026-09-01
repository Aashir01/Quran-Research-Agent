"""Identity service: users, organisations, provider keys.

Sits between the auth primitives and the API so that ownership and tenancy
rules live in one place rather than being re-implemented per route.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import ApiKeyRecord, Organisation, User
from qra.security.auth import Principal, hash_password, issue_token, verify_password
from qra.security.keys import decrypt_secret, encrypt_secret, fingerprint


class AuthError(ValueError):
    pass


def create_org(session: Session, *, slug: str, name: str, privacy_mode: str = "standard") -> Organisation:
    if privacy_mode not in ("standard", "local_only"):
        raise AuthError("privacy_mode must be 'standard' or 'local_only'")
    org = Organisation(slug=slug, name=name, privacy_mode=privacy_mode)
    session.add(org)
    session.commit()
    return org


def register_user(
    session: Session,
    *,
    email: str,
    password: str | None = None,
    display_name: str | None = None,
    role: str = "researcher",
    org_id: int | None = None,
    oidc_subject: str | None = None,
) -> User:
    if session.scalar(select(User).where(User.email == email)):
        raise AuthError(f"a user with email {email} already exists")
    # The very first user becomes an admin: a fresh deployment otherwise has
    # nobody who can grant roles.
    if session.scalar(select(func.count()).select_from(User)) == 0:
        role = "admin"
    user = User(
        email=email,
        display_name=display_name or email.split("@")[0],
        role=role,
        org_id=org_id,
        password_hash=hash_password(password) if password else None,
        oidc_subject=oidc_subject,
    )
    session.add(user)
    session.commit()
    return user


def authenticate(session: Session, *, email: str, password: str) -> str:
    user = session.scalar(select(User).where(User.email == email))
    # Verify against a dummy hash when the user is missing, so a wrong email and
    # a wrong password take the same time and cannot be distinguished.
    if user is None or not user.is_active:
        verify_password(password, hash_password("no-such-user"))
        raise AuthError("invalid credentials")
    if not verify_password(password, user.password_hash):
        raise AuthError("invalid credentials")
    return issue_token(principal_for(user))


def principal_for(user: User) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
        display_name=user.display_name,
        issuer="local",
    )


def principal_from_oidc(session: Session, claims: dict) -> Principal:
    """Map verified OIDC claims onto a local user, creating one on first sight."""
    subject = claims.get("sub")
    email = claims.get("email")
    if not subject or not email:
        raise AuthError("OIDC token lacks sub or email")
    user = session.scalar(select(User).where(User.oidc_subject == subject))
    if user is None:
        user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = register_user(
            session,
            email=email,
            display_name=claims.get("name"),
            role="researcher",
            oidc_subject=subject,
        )
    elif not user.oidc_subject:
        user.oidc_subject = subject
        session.commit()
    return principal_for(user)


def set_role(session: Session, actor: Principal, *, user_id: int, role: str) -> User:
    actor.require("admin")
    from qra.security.auth import ROLES

    if role not in ROLES:
        raise AuthError(f"role must be one of {ROLES}")
    user = session.get(User, user_id)
    if user is None:
        raise AuthError(f"user {user_id} not found")
    if actor.org_id is not None and user.org_id != actor.org_id:
        raise AuthError("cannot change a role outside your organisation")
    user.role = role
    session.commit()
    return user


# ---------------------------------------------------------------------------
# Provider keys (WP-12)
# ---------------------------------------------------------------------------


def store_provider_key(
    session: Session, principal: Principal, *, provider: str, key: str, org_wide: bool = False
) -> dict:
    """Store a provider key encrypted. Returns a fingerprint, never the key."""
    if org_wide:
        principal.require("admin")
    existing = session.scalar(
        select(ApiKeyRecord).where(
            ApiKeyRecord.provider == provider,
            ApiKeyRecord.org_id == (principal.org_id if org_wide else None),
            ApiKeyRecord.user_id == (None if org_wide else principal.user_id),
        )
    )
    record = existing or ApiKeyRecord(
        provider=provider,
        org_id=principal.org_id if org_wide else None,
        user_id=None if org_wide else principal.user_id,
    )
    record.ciphertext = encrypt_secret(key)
    record.fingerprint = fingerprint(key)
    session.add(record)
    session.commit()
    return {
        "provider": provider,
        "scope": "org" if org_wide else "user",
        "fingerprint": record.fingerprint,
    }


def resolve_provider_key(session: Session, principal: Principal | None, provider: str) -> str | None:
    """User key first, then the org default. Absent is a normal answer."""
    if principal is None:
        return None
    for filters in (
        (ApiKeyRecord.user_id == principal.user_id,),
        (ApiKeyRecord.org_id == principal.org_id, ApiKeyRecord.user_id.is_(None)),
    ):
        record = session.scalar(
            select(ApiKeyRecord).where(ApiKeyRecord.provider == provider, *filters)
        )
        if record is not None:
            return decrypt_secret(record.ciphertext)
    return None


def list_provider_keys(session: Session, principal: Principal) -> list[dict]:
    """Fingerprints only — the ciphertext never leaves this module."""
    rows = session.scalars(
        select(ApiKeyRecord).where(
            (ApiKeyRecord.user_id == principal.user_id)
            | (ApiKeyRecord.org_id == principal.org_id)
        )
    ).all()
    return [
        {
            "provider": r.provider,
            "scope": "org" if r.user_id is None else "user",
            "fingerprint": r.fingerprint,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def org_privacy_mode(session: Session, principal: Principal | None) -> str:
    if principal is None or principal.org_id is None:
        return "standard"
    org = session.get(Organisation, principal.org_id)
    return org.privacy_mode if org else "standard"


LOCAL_EMAIL = "local@localhost"


def local_user(session: Session) -> User:
    """The persisted account behind the auth-disabled bootstrap identity.

    ``bootstrap_principal`` used to carry ``user_id=0``, which is not a row in
    ``app_user`` — so every authored write (a note, a finding, a post) failed on
    the foreign key the moment auth was switched off. Since running open is a
    supported mode for a laptop, the local identity needs a real row like any
    other author.

    It is deliberately labelled rather than disguised as a person: anything this
    account wrote was written with authentication disabled, and a reviewer
    reading it later should be able to tell.
    """
    user = session.scalar(select(User).where(User.email == LOCAL_EMAIL))
    if user is None:
        user = User(
            email=LOCAL_EMAIL,
            display_name="local (auth disabled)",
            role="admin",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user
