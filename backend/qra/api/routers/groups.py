"""Study groups: private rooms, channels, threads, and a live stream.

The transport is **server-sent events**, not WebSocket. This is a one-way feed
of "something changed in this channel" — the client already has a perfectly
good way to send, which is the POST it was going to make anyway. SSE gets
automatic reconnection with `Last-Event-ID` for free, survives proxies that
mangle upgrade headers, and needs no second protocol in the deployment. A
WebSocket here would be a second connection lifecycle to get wrong in exchange
for a direction of travel nothing uses.

The stream carries **ids, not bodies**. A client that receives an id fetches
the message through the same authorised endpoint as everything else, so the
scripture guard and the membership check are never on a path that the stream
could bypass.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from qra.api.deps import principal_or_local
from qra.db import get_session, session_scope
from qra.groups import service
from qra.groups.service import GroupAccessError, GroupError
from qra.security.auth import Principal

router = APIRouter(prefix="/groups", tags=["groups"])

# In-process fan-out. One queue per connected listener, keyed by channel.
#
# Deliberately not a message broker: a single-team deployment is the target, and
# a Redis dependency to deliver "message 41 arrived" to four people in a room is
# a lot of operational surface for very little. `/groups/meta` reports that this
# is process-local so a multi-worker deployment cannot mistake it for one that
# fans out across workers — the honest version of a limitation is a stated one.
_LISTENERS: dict[int, set[asyncio.Queue]] = defaultdict(set)
MAX_LISTENERS_PER_CHANNEL = 64
HEARTBEAT_SECONDS = 25


def publish(channel_id: int, event: str, payload: dict) -> None:
    """Tell every listener on this channel that something happened."""
    for queue in list(_LISTENERS.get(channel_id, ())):
        try:
            queue.put_nowait({"event": event, "data": payload})
        except asyncio.QueueFull:
            # A listener too slow to keep up is dropped rather than allowed to
            # apply backpressure to the writer. It will resync on reconnect.
            _LISTENERS[channel_id].discard(queue)


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, GroupAccessError):
        # "No such group" for a non-member and for a non-existent group alike:
        # confirming that a private group exists is itself a disclosure.
        status = 404 if "no such" in str(exc) else 403
        return HTTPException(status, str(exc))
    # A scripture-guard refusal carries the offending runs and the reference the
    # author should have cited. Flattening it to a string here would leave them
    # with a rejection and no way to act on it — so it goes back structured, the
    # same shape the commons uses, and the composer can offer the fix.
    violations = getattr(exc, "violations", None)
    if violations:
        return HTTPException(
            422,
            detail={
                "message": str(exc),
                "violations": violations,
                "suggestions": getattr(exc, "suggestions", []),
            },
        )
    return HTTPException(422, str(exc))


# --- groups ----------------------------------------------------------------


@router.get("")
def my_groups(
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    return {
        "groups": service.list_groups(session, principal),
        "invitations": service.pending_invites(session, principal),
    }


@router.post("")
def create_group(
    name: str = Body(...),
    purpose: str = Body(""),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.create_group(session, principal, name=name, purpose=purpose)
    except GroupError as exc:
        raise _handle(exc) from exc


@router.get("/meta")
def meta() -> dict:
    """What this feature does and does not guarantee."""
    return {
        "realtime": "sse",
        "why_not_websocket": (
            "The stream is one-way — the client already sends over HTTP. SSE reconnects "
            "itself, survives proxies, and adds no second protocol to the deployment."
        ),
        "fanout": "in-process",
        "fanout_limitation": (
            "Listeners are held in the worker process, so live updates reach only clients "
            "connected to the same worker. A multi-worker deployment needs a shared bus "
            "before this is true real-time across all of them. Polling the channel still "
            "returns correct data everywhere; only the push is process-local."
        ),
        "scripture_guard": "strict on every message body and channel topic, same as the commons",
        "reactions_not_votes": (
            "A vote ranks. Ranking a colleague's half-formed thought changes what people "
            "are willing to say in a room, so a group has reactions and no scoring."
        ),
    }


@router.get("/{group_id}/members")
def members(
    group_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> list[dict]:
    try:
        return service.members(session, principal, group_id)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/{group_id}/invite")
def invite(
    group_id: int,
    email: str = Body(...),
    role: str = Body("member"),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.invite(session, principal, group_id, email=email, role=role)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/{group_id}/accept")
def accept(
    group_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.accept_invite(session, principal, group_id)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/{group_id}/role")
def set_role(
    group_id: int,
    user_id: int = Body(...),
    role: str = Body(...),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.set_role(session, principal, group_id, user_id=user_id, role=role)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


# --- channels --------------------------------------------------------------


@router.get("/{group_id}/channels")
def channels(
    group_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> list[dict]:
    try:
        return service.list_channels(session, principal, group_id)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/{group_id}/channels")
def create_channel(
    group_id: int,
    name: str = Body(...),
    topic: str = Body(""),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.create_channel(session, principal, group_id, name=name, topic=topic)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/channels/{channel_id}/topic")
def set_topic(
    channel_id: int,
    topic: str = Body(..., embed=True),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        payload = service.set_topic(session, principal, channel_id, topic=topic)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc
    publish(channel_id, "topic", {"channel_id": channel_id})
    return payload


# --- messages --------------------------------------------------------------


@router.get("/channels/{channel_id}/messages")
def read_channel(
    channel_id: int,
    limit: int = 60,
    before_id: int | None = None,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.read_channel(
            session, principal, channel_id, limit=min(limit, 200), before_id=before_id
        )
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/channels/{channel_id}/messages")
def post_message(
    channel_id: int,
    body: str = Body(...),
    parent_id: int | None = Body(None),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        message = service.post_message(
            session, principal, channel_id, body=body, parent_id=parent_id
        )
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc
    publish(
        channel_id,
        "message",
        {"id": message["id"], "parent_id": message["parent_id"], "channel_id": channel_id},
    )
    return message


@router.get("/messages/{message_id}/thread")
def thread(
    message_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.thread(session, principal, message_id)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc


@router.post("/messages/{message_id}/react")
def react(
    message_id: int,
    emoji: str = Body(..., embed=True),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        payload = service.react(session, principal, message_id, emoji=emoji)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc
    publish(payload["channel_id"], "reaction", {"id": message_id})
    return payload


@router.patch("/messages/{message_id}")
def edit_message(
    message_id: int,
    body: str = Body(..., embed=True),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        payload = service.edit_message(session, principal, message_id, body=body)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc
    publish(payload["channel_id"], "message", {"id": message_id})
    return payload


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        payload = service.delete_message(session, principal, message_id)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc
    publish(payload["channel_id"], "message", {"id": message_id})
    return payload


@router.post("/messages/{message_id}/pin")
def pin(
    message_id: int,
    pinned: bool = Body(True, embed=True),
    principal: Principal = Depends(principal_or_local),
    session: Session = Depends(get_session),
) -> dict:
    try:
        payload = service.pin(session, principal, message_id, pinned=pinned)
    except (GroupError, GroupAccessError) as exc:
        raise _handle(exc) from exc
    publish(payload["channel_id"], "message", {"id": message_id})
    return payload


# --- the live stream -------------------------------------------------------


@router.get("/channels/{channel_id}/stream")
async def stream(
    channel_id: int,
    request: Request,
    principal: Principal = Depends(principal_or_local),
) -> StreamingResponse:
    """Server-sent events for one channel.

    Membership is checked **before** the stream opens, on its own session — the
    request-scoped session would otherwise stay open for the life of the
    connection, holding a pooled database handle idle for hours.
    """
    with session_scope() as session:
        try:
            service.membership(session, _group_of(session, channel_id), principal)
        except GroupAccessError as exc:
            raise _handle(exc) from exc

    if len(_LISTENERS[channel_id]) >= MAX_LISTENERS_PER_CHANNEL:
        raise HTTPException(503, "too many listeners on this channel")

    queue: asyncio.Queue = asyncio.Queue(maxsize=128)
    _LISTENERS[channel_id].add(queue)

    async def events():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    # A comment line. Keeps intermediaries from timing the
                    # connection out, and costs one byte more than nothing.
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
        finally:
            _LISTENERS[channel_id].discard(queue)
            if not _LISTENERS[channel_id]:
                _LISTENERS.pop(channel_id, None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache, no-transform",
            # nginx buffers by default, which turns a live stream into a
            # batch delivered whenever the buffer happens to flush.
            "x-accel-buffering": "no",
            "connection": "keep-alive",
        },
    )


def _group_of(session: Session, channel_id: int) -> int:
    from sqlalchemy import select

    from qra.models import Channel

    group_id = session.scalar(select(Channel.group_id).where(Channel.id == channel_id))
    if group_id is None:
        raise GroupAccessError("no such channel")
    return group_id
