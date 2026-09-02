"""Study groups: private rooms, channels, threads.

A room is a different thing from a feed, and most of these tests are about the
ways it is different — membership that is explicit rather than discoverable,
reactions instead of votes, deletion that leaves a tombstone.

The one thing that is *not* different is the scripture guard. A private room is
not a reason to relax it: a fabricated ayah quoted in a study group is quoted by
someone the group trusts, and it leaves the room in a screenshot.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from qra.groups import service
from qra.groups.service import GroupAccessError, GroupError
from qra.security.auth import Principal

REAL_REFERENCE = "Look at {{ayah:2:255}} — the pronoun shift is the thing."
FABRICATED = "وَقَالَ ٱلرَّحْمَٰنُ إِنَّ ٱلْعِلْمَ نُورٌ وَٱلْجَهْلَ ظُلْمَةٌ فَٱتَّقُوا۟ رَبَّكُمْ"


def _principal(session, email: str) -> Principal:
    from qra.models import User
    from qra.security.service import register_user

    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = register_user(
            session,
            email=email,
            password="pw-for-tests-1234",
            display_name=email.split("@")[0],
        )
        session.commit()
    return Principal(
        user_id=user.id,
        email=user.email,
        role="researcher",
        org_id=None,
        display_name=user.display_name,
        issuer="test",
    )


@pytest.fixture(autouse=True)
def _leave_no_trace(session):
    """Groups are private rooms; test rooms should not outlive the test."""
    from qra.models import (
        Channel,
        GroupMember,
        Message,
        MessageReaction,
        StudyGroup,
    )

    models = (MessageReaction, Message, Channel, GroupMember, StudyGroup)
    high = {model: session.scalar(select(func.max(model.id))) or 0 for model in models}
    yield
    for model in models:
        session.query(model).filter(model.id > high[model]).delete(
            synchronize_session=False
        )
    session.commit()


@pytest.fixture
def owner(session):
    return _principal(session, "group-owner@example.org")


@pytest.fixture
def colleague(session):
    return _principal(session, "group-colleague@example.org")


@pytest.fixture
def outsider(session):
    return _principal(session, "group-outsider@example.org")


@pytest.fixture
def group(session, owner):
    return service.create_group(
        session, owner, name="Nazm reading circle", purpose="Working through surah 12"
    )


@pytest.fixture
def channel(session, owner, group):
    return service.list_channels(session, owner, group["id"])[0]


# --- the scripture guard, unchanged in private -----------------------------


def test_a_message_may_quote_by_reference(session, owner, channel):
    message = service.post_message(session, owner, channel["id"], body=REAL_REFERENCE)
    assert "{{" not in message["body_rendered"]
    assert message["citations"]
    assert message["ayah_ids"]


def test_fabricated_scripture_is_refused_in_a_private_room(session, owner, channel):
    """The load-bearing test. Privacy is not a reason to relax this — a verse
    invented here is quoted by people who trust the room."""
    with pytest.raises(GroupError) as caught:
        service.post_message(session, owner, channel["id"], body=f"Consider {FABRICATED}")
    assert caught.value.violations


def test_a_channel_topic_goes_through_the_same_guard(session, owner, group):
    with pytest.raises(GroupError):
        service.create_channel(
            session, owner, group["id"], name="bad", topic=FABRICATED
        )
    good = service.create_channel(
        session, owner, group["id"], name="Surah 12", topic="Start at {{ayah:12:3}}."
    )
    assert good["topic_rendered"]
    assert "{{" not in good["topic_rendered"]


def test_an_edit_cannot_smuggle_scripture_past_the_guard(session, owner, channel):
    """Write clean, edit dirty is the obvious way round a write-time check."""
    message = service.post_message(session, owner, channel["id"], body="Placeholder.")
    with pytest.raises(GroupError):
        service.edit_message(session, owner, message["id"], body=FABRICATED)


# --- membership is explicit ------------------------------------------------


def test_a_non_member_cannot_tell_the_group_exists(session, outsider, group):
    """Not a member and not a group are answered identically. 'That exists but
    you cannot see it' discloses the thing a private space withholds."""
    with pytest.raises(GroupAccessError, match="no such group"):
        service.members(session, outsider, group["id"])


def test_an_invitation_is_pending_until_accepted(session, owner, colleague, group):
    result = service.invite(session, owner, group["id"], email=colleague.email)
    assert result["invited"] is True

    # Invited is not joined. The group must not appear in their list yet.
    assert group["id"] not in {g["id"] for g in service.list_groups(session, colleague)}
    with pytest.raises(GroupAccessError):
        service.membership(session, group["id"], colleague)

    pending = service.pending_invites(session, colleague)
    assert group["id"] in {p["group_id"] for p in pending}

    service.accept_invite(session, colleague, group["id"])
    assert group["id"] in {g["id"] for g in service.list_groups(session, colleague)}


def test_only_an_owner_can_invite(session, colleague, owner, group):
    service.invite(session, owner, group["id"], email=colleague.email)
    service.accept_invite(session, colleague, group["id"])
    with pytest.raises(GroupAccessError, match="owner"):
        service.invite(session, colleague, group["id"], email="someone@example.org")


def test_a_reader_cannot_write(session, owner, colleague, group, channel):
    service.invite(session, owner, group["id"], email=colleague.email, role="reader")
    service.accept_invite(session, colleague, group["id"])
    assert service.read_channel(session, colleague, channel["id"])["your_role"] == "reader"
    with pytest.raises(GroupAccessError, match="member"):
        service.post_message(session, colleague, channel["id"], body="hello")


def test_a_group_cannot_be_left_without_an_owner(session, owner, group):
    with pytest.raises(GroupError, match="needs an owner"):
        service.set_role(
            session, owner, group["id"], user_id=owner.user_id, role="member"
        )


# --- channels and threads --------------------------------------------------


def test_a_new_group_gets_a_channel(session, owner, group):
    """A group with no channel is a room with no doors."""
    channels = service.list_channels(session, owner, group["id"])
    assert [c["name"] for c in channels] == ["general"]


def test_replies_form_one_thread_not_a_tree(session, owner, channel):
    """A reply to a reply joins the same thread. Deep trees are where a
    discussion goes to become unreadable."""
    root = service.post_message(session, owner, channel["id"], body="The question.")
    first = service.post_message(
        session, owner, channel["id"], body="An answer.", parent_id=root["id"]
    )
    second = service.post_message(
        session, owner, channel["id"], body="On that answer.", parent_id=first["id"]
    )
    assert first["parent_id"] == root["id"]
    assert second["parent_id"] == root["id"]
    assert len(service.thread(session, owner, root["id"])["replies"]) == 2


def test_the_channel_view_shows_roots_only(session, owner, channel):
    root = service.post_message(session, owner, channel["id"], body="Root message.")
    service.post_message(session, owner, channel["id"], body="Reply.", parent_id=root["id"])
    listed = service.read_channel(session, owner, channel["id"])["messages"]
    assert [m["id"] for m in listed] == [root["id"]]
    assert listed[0]["reply_count"] == 1


# --- reactions, not votes --------------------------------------------------


def test_reactions_do_not_score_anything(session, owner, channel):
    """A vote ranks. Ranking a colleague's half-formed thought changes what
    people are willing to say in a room, so there is no score to sort by."""
    message = service.post_message(session, owner, channel["id"], body="A thought.")
    reacted = service.react(session, owner, message["id"], emoji="👍")
    assert reacted["reactions"] == [{"emoji": "👍", "count": 1}]
    assert "score" not in reacted
    assert "votes" not in reacted

    # Same reaction again removes it.
    assert service.react(session, owner, message["id"], emoji="👍")["reactions"] == []


# --- deletion leaves a mark ------------------------------------------------


def test_a_removed_message_leaves_a_tombstone(session, owner, channel):
    """A thread that silently loses a message reads as though it never had one,
    and in a discussion of evidence that is its own kind of falsification."""
    root = service.post_message(session, owner, channel["id"], body="The question.")
    reply = service.post_message(
        session, owner, channel["id"], body="Withdrawn.", parent_id=root["id"]
    )
    removed = service.delete_message(session, owner, reply["id"])
    assert removed["removed"] is True
    assert removed["body"] is None
    assert removed["body_rendered"] == "[removed]"

    replies = service.thread(session, owner, root["id"])["replies"]
    assert [r["id"] for r in replies] == [reply["id"]]


def test_you_cannot_remove_someone_elses_message(session, owner, colleague, group, channel):
    service.invite(session, owner, group["id"], email=colleague.email)
    service.accept_invite(session, colleague, group["id"])
    mine = service.post_message(session, owner, channel["id"], body="Mine.")
    with pytest.raises(GroupAccessError, match="your own"):
        service.delete_message(session, colleague, mine["id"])


def test_a_moderator_can_remove_any_message(session, owner, colleague, group, channel):
    service.invite(session, owner, group["id"], email=colleague.email, role="moderator")
    service.accept_invite(session, colleague, group["id"])
    mine = service.post_message(session, owner, channel["id"], body="Mine.")
    assert service.delete_message(session, colleague, mine["id"])["removed"] is True


# --- the API surface -------------------------------------------------------


def test_a_guard_refusal_reaches_the_client_structured(session):
    """A rejection with no way to act on it is half a feature. The offending
    runs come back, the same shape the commons uses.

    The room is created *through the API* rather than reused from the fixture:
    the fixture's owner is a different user, and the call would be refused with
    a 404 before it ever reached the guard — which is the access control working
    and would make this a test of the wrong thing.
    """
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        group = client.post("/groups", json={"name": "Guard check"}).json()
        channel = client.get(f"/groups/{group['id']}/channels").json()[0]
        response = client.post(
            f"/groups/channels/{channel['id']}/messages",
            json={"body": f"Consider {FABRICATED}"},
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["violations"]
    assert "did not come from the corpus" in detail["message"]


def test_the_realtime_limitation_is_stated_rather_than_implied(session):
    """In-process fan-out reaches only clients on the same worker. The honest
    version of a limitation is a stated one."""
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        meta = client.get("/groups/meta").json()
    assert meta["realtime"] == "sse"
    assert meta["fanout"] == "in-process"
    assert "multi-worker" in meta["fanout_limitation"]


def test_the_stream_publishes_an_id_not_a_body(session, owner, channel):
    """The stream carries ids so a client re-fetches through the authorised
    endpoint. A body on the wire is a body that skipped the membership check."""
    import asyncio

    from qra.api.routers.groups import _LISTENERS, publish

    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    _LISTENERS[channel["id"]].add(queue)
    try:
        message = service.post_message(session, owner, channel["id"], body="Hello.")
        publish(
            channel["id"],
            "message",
            {"id": message["id"], "parent_id": None, "channel_id": channel["id"]},
        )
        item = queue.get_nowait()
        assert item["event"] == "message"
        assert set(item["data"]) == {"id", "parent_id", "channel_id"}
        assert "body" not in item["data"]
    finally:
        _LISTENERS[channel["id"]].discard(queue)


def test_a_stranger_gets_a_404_from_the_api_not_a_403(session, owner, channel):
    """Through the API too: the local principal is not in this room, and the
    answer must not distinguish "not yours" from "does not exist"."""
    from fastapi.testclient import TestClient

    from qra.api.main import app

    with TestClient(app) as client:
        response = client.post(
            f"/groups/channels/{channel['id']}/messages", json={"body": "Hello."}
        )
    assert response.status_code == 404
    assert "no such" in response.json()["detail"]
