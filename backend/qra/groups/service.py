"""Study groups (WP-38 in spirit; requested directly).

A commons and a room are different things, and the difference is not privacy
settings. In the commons a researcher is publishing; in a room they are
thinking aloud with people they chose. Both are necessary and neither is a
weaker version of the other, so this is a separate model rather than a
visibility flag on ``Post``.

What carries over unchanged is the scripture guard. Every message body goes
through the same :func:`qra.agents.render.render` in strict mode that governs
public posts and agent output. A private room is not a reason to relax it —
arguably the reverse. A fabricated ayah quoted in a study group is quoted by
someone the group trusts, it will be repeated with that trust attached, and it
leaves the room in a screenshot.

What is deliberately different:

* **Reactions, not votes.** A vote ranks. A room does not need ranking, and
  scoring a colleague's half-formed thought changes what people are willing to
  say in one.
* **Membership is explicit.** No discovery, no join-by-link, no public listing.
  Invitations are by email and stay pending until accepted, so a group's member
  list is never a list of people who did not agree to be in it.
* **Deletion is a tombstone.** A removed message leaves a marker, because a
  thread that silently loses a message reads as though it never had one — and
  in a discussion of evidence that is its own kind of falsification.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.community.service import CommunityError, _anchors, _prepare_body
from qra.models import (
    Channel,
    GroupMember,
    Message,
    MessageReaction,
    StudyGroup,
    User,
)
from qra.security.auth import Principal

ROLES = ("owner", "moderator", "member", "reader")
_RANK = {role: index for index, role in enumerate(reversed(ROLES))}

MAX_MEMBERS = 200
MAX_CHANNELS = 60
SLUG_RE = re.compile(r"[^a-z0-9]+")


class GroupError(ValueError):
    """A group rule was broken. Carries which one.

    ``violations`` and ``suggestions`` are populated when the break was the
    scripture guard: the offending runs, and the placeholder the author should
    have used. Flattening that to a string would throw away the half that lets
    them fix the message.
    """

    def __init__(
        self,
        message: str,
        *,
        violations: list | None = None,
        suggestions: list | None = None,
    ):
        super().__init__(message)
        self.violations = violations or []
        self.suggestions = suggestions or []


class GroupAccessError(PermissionError):
    """The caller is not entitled to this group, or not at this level.

    Distinct from :class:`GroupError` because the API must answer it with 403 —
    and, for a caller who is not a member at all, with 404: confirming that a
    private group exists is itself a disclosure.
    """


def _guard(session: Session, body: str) -> tuple[str, list[dict]]:
    """Run the commons' scripture guard and speak this module's error language.

    The guard is shared on purpose — one door for every human-typed body in the
    application — but it raises ``CommunityError``, and a groups route that only
    catches ``GroupError`` would let a *correct* refusal escape as a 500. The
    guard would be working and the user would see a crash.
    """
    try:
        return _prepare_body(session, body)
    except CommunityError as exc:
        raise GroupError(
            str(exc),
            violations=getattr(exc, "violations", []),
            suggestions=getattr(exc, "suggestions", []),
        ) from exc


def _slug(text: str) -> str:
    base = SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return base[:56] or "group"


def _unique_slug(session: Session, model, text: str, **scope) -> str:
    base = _slug(text)
    candidate = base
    suffix = 2
    while session.scalar(
        select(model.id).filter_by(slug=candidate, **scope)
    ) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


# ---------------------------------------------------------------------------
# Membership — the gate every other function goes through
# ---------------------------------------------------------------------------


def membership(session: Session, group_id: int, principal: Principal) -> GroupMember:
    """The caller's membership, or a 404-shaped refusal.

    Not being a member and the group not existing are answered identically on
    purpose. "That group exists but you cannot see it" tells a stranger that a
    group by that name exists, which is exactly the thing a private space is
    for withholding.
    """
    row = session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == principal.user_id,
            GroupMember.accepted_at.is_not(None),
        )
    )
    if row is None:
        raise GroupAccessError("no such group")
    return row


def _require(session: Session, group_id: int, principal: Principal, role: str) -> GroupMember:
    member = membership(session, group_id, principal)
    if _RANK.get(member.role, -1) < _RANK.get(role, 99):
        raise GroupAccessError(
            f"this needs the '{role}' role in this group; you have '{member.role}'"
        )
    return member


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def create_group(
    session: Session, principal: Principal, *, name: str, purpose: str = ""
) -> dict:
    if not (name or "").strip():
        raise GroupError("a group needs a name")

    group = StudyGroup(
        slug=_unique_slug(session, StudyGroup, name),
        name=name.strip(),
        purpose=purpose.strip(),
        owner_id=principal.user_id,
    )
    session.add(group)
    session.flush()
    session.add(
        GroupMember(
            group_id=group.id,
            user_id=principal.user_id,
            role="owner",
            accepted_at=datetime.now(UTC),
        )
    )
    # A group with no channel is a room with no doors. One is created so the
    # first message does not require a second act of configuration.
    session.add(
        Channel(
            group_id=group.id,
            slug="general",
            name="general",
            topic="",
            topic_rendered="",
            created_by_id=principal.user_id,
            position=0,
        )
    )
    session.commit()
    session.refresh(group)
    return serialise_group(session, group, role="owner")


def list_groups(session: Session, principal: Principal) -> list[dict]:
    """Only groups the caller has actually accepted into."""
    rows = session.execute(
        select(StudyGroup, GroupMember)
        .join(GroupMember, GroupMember.group_id == StudyGroup.id)
        .where(
            GroupMember.user_id == principal.user_id,
            GroupMember.accepted_at.is_not(None),
        )
        .order_by(StudyGroup.created_at.desc())
    ).all()
    return [serialise_group(session, group, role=member.role) for group, member in rows]


def pending_invites(session: Session, principal: Principal) -> list[dict]:
    rows = session.execute(
        select(StudyGroup, GroupMember)
        .join(GroupMember, GroupMember.group_id == StudyGroup.id)
        .where(
            GroupMember.accepted_at.is_(None),
            (GroupMember.user_id == principal.user_id)
            | (func.lower(GroupMember.invited_email) == (principal.email or "").lower()),
        )
    ).all()
    return [
        {
            "group_id": group.id,
            "name": group.name,
            "purpose": group.purpose,
            "role": member.role,
            "invited_at": member.created_at.isoformat(),
        }
        for group, member in rows
    ]


def serialise_group(session: Session, group: StudyGroup, *, role: str) -> dict:
    counts = session.execute(
        select(
            func.count(GroupMember.id).filter(GroupMember.accepted_at.is_not(None)),
            func.count(GroupMember.id).filter(GroupMember.accepted_at.is_(None)),
        ).where(GroupMember.group_id == group.id)
    ).one()
    return {
        "id": group.id,
        "slug": group.slug,
        "name": group.name,
        "purpose": group.purpose,
        "your_role": role,
        "members": counts[0],
        "pending_invites": counts[1],
        "channels": session.scalar(
            select(func.count())
            .select_from(Channel)
            .where(Channel.group_id == group.id, Channel.archived_at.is_(None))
        )
        or 0,
        "archived": group.archived_at is not None,
        "created_at": group.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def invite(
    session: Session, principal: Principal, group_id: int, *, email: str, role: str = "member"
) -> dict:
    """Invite by email. Pending until accepted — never auto-joined."""
    _require(session, group_id, principal, "owner")
    if role not in ROLES or role == "owner":
        raise GroupError(f"role must be one of {', '.join(r for r in ROLES if r != 'owner')}")

    address = (email or "").strip().lower()
    if "@" not in address:
        raise GroupError(f"'{email}' is not an email address")

    total = (
        session.scalar(
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
        )
        or 0
    )
    if total >= MAX_MEMBERS:
        raise GroupError(f"a group holds at most {MAX_MEMBERS} people")

    user = session.scalar(select(User).where(func.lower(User.email) == address))
    existing = session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            (GroupMember.user_id == user.id)
            if user
            else (func.lower(GroupMember.invited_email) == address),
        )
    )
    if existing is not None:
        return {
            "invited": False,
            "already": "member" if existing.accepted_at else "invited",
            "email": address,
        }

    session.add(
        GroupMember(
            group_id=group_id,
            user_id=user.id if user else None,
            invited_email=address,
            role=role,
            invited_by_id=principal.user_id,
        )
    )
    session.commit()
    return {
        "invited": True,
        "email": address,
        "role": role,
        "has_account": user is not None,
        "note": (
            "Pending until they accept. A group's member list should never be a list of "
            "people who did not agree to be in it."
        ),
    }


def accept_invite(session: Session, principal: Principal, group_id: int) -> dict:
    row = session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.accepted_at.is_(None),
            (GroupMember.user_id == principal.user_id)
            | (func.lower(GroupMember.invited_email) == (principal.email or "").lower()),
        )
    )
    if row is None:
        raise GroupAccessError("no pending invitation for you in that group")
    row.user_id = principal.user_id
    row.accepted_at = datetime.now(UTC)
    session.commit()
    group = session.get(StudyGroup, group_id)
    return serialise_group(session, group, role=row.role)


def members(session: Session, principal: Principal, group_id: int) -> list[dict]:
    membership(session, group_id, principal)
    rows = session.execute(
        select(GroupMember, User)
        .outerjoin(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.created_at)
    ).all()
    return [
        {
            "user_id": member.user_id,
            "display_name": user.display_name if user else None,
            "email": (user.email if user else member.invited_email),
            "role": member.role,
            "accepted": member.accepted_at is not None,
        }
        for member, user in rows
    ]


def set_role(
    session: Session, principal: Principal, group_id: int, *, user_id: int, role: str
) -> dict:
    _require(session, group_id, principal, "owner")
    if role not in ROLES:
        raise GroupError(f"role must be one of {', '.join(ROLES)}")
    row = session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )
    if row is None:
        raise GroupError("that person is not in this group")
    if row.role == "owner" and role != "owner":
        remaining = session.scalar(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == group_id, GroupMember.role == "owner")
        )
        if (remaining or 0) <= 1:
            raise GroupError(
                "a group needs an owner. Promote someone else before stepping down."
            )
    row.role = role
    session.commit()
    return {"user_id": user_id, "role": role}


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


def create_channel(
    session: Session,
    principal: Principal,
    group_id: int,
    *,
    name: str,
    topic: str = "",
) -> dict:
    """Open a channel. The topic goes through the scripture guard like any body."""
    _require(session, group_id, principal, "moderator")
    if not (name or "").strip():
        raise GroupError("a channel needs a name")

    open_channels = (
        session.scalar(
            select(func.count())
            .select_from(Channel)
            .where(Channel.group_id == group_id, Channel.archived_at.is_(None))
        )
        or 0
    )
    if open_channels >= MAX_CHANNELS:
        raise GroupError(f"a group holds at most {MAX_CHANNELS} open channels")

    rendered, citations = _guard(session, topic) if topic.strip() else ("", [])
    channel = Channel(
        group_id=group_id,
        slug=_unique_slug(session, Channel, name, group_id=group_id),
        name=name.strip()[:120],
        topic=topic,
        topic_rendered=rendered,
        topic_citations=citations,
        created_by_id=principal.user_id,
        position=open_channels,
    )
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return serialise_channel(session, channel)


def list_channels(session: Session, principal: Principal, group_id: int) -> list[dict]:
    membership(session, group_id, principal)
    rows = session.scalars(
        select(Channel)
        .where(Channel.group_id == group_id, Channel.archived_at.is_(None))
        .order_by(Channel.position, Channel.id)
    ).all()
    return [serialise_channel(session, channel) for channel in rows]


def serialise_channel(session: Session, channel: Channel) -> dict:
    return {
        "id": channel.id,
        "group_id": channel.group_id,
        "slug": channel.slug,
        "name": channel.name,
        "topic": channel.topic,
        "topic_rendered": channel.topic_rendered,
        "topic_citations": channel.topic_citations or [],
        "messages": session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.channel_id == channel.id, Message.deleted_at.is_(None))
        )
        or 0,
        "created_at": channel.created_at.isoformat(),
    }


def set_topic(
    session: Session, principal: Principal, channel_id: int, *, topic: str
) -> dict:
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise GroupAccessError("no such channel")
    _require(session, channel.group_id, principal, "moderator")
    rendered, citations = _guard(session, topic) if topic.strip() else ("", [])
    channel.topic = topic
    channel.topic_rendered = rendered
    channel.topic_citations = citations
    session.commit()
    return serialise_channel(session, channel)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def post_message(
    session: Session,
    principal: Principal,
    channel_id: int,
    *,
    body: str,
    parent_id: int | None = None,
) -> dict:
    """Write into a channel, or into a thread under one message.

    The body goes through the same strict render as a public post. Being in a
    private room is not a reason to relax the scripture rule.
    """
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise GroupAccessError("no such channel")
    _require(session, channel.group_id, principal, "member")
    if not (body or "").strip():
        raise GroupError("a message needs a body")

    parent = None
    if parent_id is not None:
        parent = session.get(Message, parent_id)
        if parent is None or parent.channel_id != channel_id:
            raise GroupError("that message is not in this channel")
        # One level of threading. A reply to a reply joins the same thread
        # rather than starting a nested one — deep trees are where discussions
        # go to become unreadable.
        parent_id = parent.parent_id or parent.id

    rendered, citations = _guard(session, body)
    ayah_ids, _roots = _anchors(body)
    message = Message(
        channel_id=channel_id,
        group_id=channel.group_id,
        author_id=principal.user_id,
        parent_id=parent_id,
        body=body,
        body_rendered=rendered,
        citations=citations,
        ayah_ids=ayah_ids,
    )
    session.add(message)
    session.flush()
    if parent_id is not None:
        root = session.get(Message, parent_id)
        root.reply_count = (root.reply_count or 0) + 1
    session.commit()
    session.refresh(message)
    return serialise_message(session, message)


def read_channel(
    session: Session,
    principal: Principal,
    channel_id: int,
    *,
    limit: int = 60,
    before_id: int | None = None,
) -> dict:
    """Top-level messages, newest last. Threaded replies are fetched separately."""
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise GroupAccessError("no such channel")
    member = _require(session, channel.group_id, principal, "reader")

    stmt = select(Message).where(
        Message.channel_id == channel_id, Message.parent_id.is_(None)
    )
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    rows = session.scalars(stmt.order_by(Message.id.desc()).limit(limit)).all()

    member.last_read_at = datetime.now(UTC)
    session.commit()

    ordered = list(reversed(rows))
    return {
        "channel": serialise_channel(session, channel),
        "messages": [serialise_message(session, m) for m in ordered],
        "has_more": len(rows) == limit,
        "oldest_id": ordered[0].id if ordered else None,
        "your_role": member.role,
    }


def thread(session: Session, principal: Principal, message_id: int) -> dict:
    root = session.get(Message, message_id)
    if root is None:
        raise GroupAccessError("no such message")
    _require(session, root.group_id, principal, "reader")
    replies = session.scalars(
        select(Message).where(Message.parent_id == root.id).order_by(Message.id)
    ).all()
    return {
        "root": serialise_message(session, root),
        "replies": [serialise_message(session, m) for m in replies],
    }


def edit_message(
    session: Session, principal: Principal, message_id: int, *, body: str
) -> dict:
    message = session.get(Message, message_id)
    if message is None:
        raise GroupAccessError("no such message")
    _require(session, message.group_id, principal, "member")
    if message.author_id != principal.user_id:
        raise GroupAccessError("you can only edit your own messages")
    rendered, citations = _guard(session, body)
    message.body = body
    message.body_rendered = rendered
    message.citations = citations
    message.ayah_ids = _anchors(body)[0]
    message.edited_at = datetime.now(UTC)
    session.commit()
    return serialise_message(session, message)


def delete_message(session: Session, principal: Principal, message_id: int) -> dict:
    """Tombstone, never a hole.

    A thread that silently loses a message reads as though it never had one, and
    in a discussion of evidence that is its own kind of falsification. The row
    stays and the reply count stays correct; only the body goes.
    """
    message = session.get(Message, message_id)
    if message is None:
        raise GroupAccessError("no such message")
    member = membership(session, message.group_id, principal)
    is_moderator = _RANK.get(member.role, -1) >= _RANK["moderator"]
    if message.author_id != principal.user_id and not is_moderator:
        raise GroupAccessError("you can only remove your own messages")
    message.deleted_at = datetime.now(UTC)
    session.commit()
    return serialise_message(session, message)


def pin(session: Session, principal: Principal, message_id: int, *, pinned: bool = True) -> dict:
    message = session.get(Message, message_id)
    if message is None:
        raise GroupAccessError("no such message")
    _require(session, message.group_id, principal, "moderator")
    message.pinned = pinned
    session.commit()
    return serialise_message(session, message)


def react(
    session: Session, principal: Principal, message_id: int, *, emoji: str
) -> dict:
    """Toggle one reaction.

    Reactions rather than votes, deliberately. A vote ranks, and ranking a
    colleague's half-formed thought changes what people are willing to say in a
    room. This is acknowledgement, and it does not sort anything.
    """
    message = session.get(Message, message_id)
    if message is None:
        raise GroupAccessError("no such message")
    _require(session, message.group_id, principal, "member")
    glyph = (emoji or "").strip()[:16]
    if not glyph:
        raise GroupError("a reaction needs an emoji")

    existing = session.scalar(
        select(MessageReaction).where(
            MessageReaction.message_id == message_id,
            MessageReaction.user_id == principal.user_id,
            MessageReaction.emoji == glyph,
        )
    )
    if existing is not None:
        session.delete(existing)
    else:
        session.add(
            MessageReaction(message_id=message_id, user_id=principal.user_id, emoji=glyph)
        )
    session.commit()
    return serialise_message(session, message)


def _reactions(session: Session, message_id: int) -> list[dict]:
    rows = session.execute(
        select(MessageReaction.emoji, func.count())
        .where(MessageReaction.message_id == message_id)
        .group_by(MessageReaction.emoji)
        .order_by(func.count().desc())
    ).all()
    return [{"emoji": emoji, "count": count} for emoji, count in rows]


def serialise_message(session: Session, message: Message) -> dict:
    author = session.get(User, message.author_id)
    removed = message.deleted_at is not None
    return {
        "id": message.id,
        "channel_id": message.channel_id,
        "parent_id": message.parent_id,
        "author": {
            "id": message.author_id,
            "display_name": author.display_name if author else "unknown",
            "role": author.role if author else None,
        },
        # A removed message keeps its place in the thread. The marker is the
        # point: a silently vanished message is a falsified record.
        "removed": removed,
        "body": None if removed else message.body,
        "body_rendered": (
            "[removed]" if removed else message.body_rendered
        ),
        "citations": [] if removed else (message.citations or []),
        "ayah_ids": [] if removed else (message.ayah_ids or []),
        "reactions": [] if removed else _reactions(session, message.id),
        "reply_count": message.reply_count or 0,
        "pinned": message.pinned,
        "edited": message.edited_at is not None,
        "created_at": message.created_at.isoformat(),
    }
