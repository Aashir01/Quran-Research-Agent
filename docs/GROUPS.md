# Study groups

Private rooms with channels and threaded discussion, alongside the public
commons. Two surfaces, because a commons and a room are different things and
neither is a weaker version of the other: in the commons a researcher is
publishing, in a room they are thinking aloud with people they chose.

That is why this is a separate model rather than a visibility flag on `Post`.

## What carries over

**The scripture guard, unchanged.** Every message body and every channel topic
goes through the same strict `render()` that governs public posts and agent
output. Fabricated Arabic is a write-time rejection, and the rejection carries
the offending runs plus the placeholder the author should have used — the
composer offers the fix in one click.

Being private is not a reason to relax this. Arguably the reverse: a fabricated
ayah quoted in a study group is quoted by someone the group trusts, it will be
repeated with that trust attached, and it leaves the room in a screenshot.

The guard raises `CommunityError`; `qra.groups.service._guard` translates it to
a `GroupError` carrying the same payload. Without that translation a *correct*
refusal escapes the router as a 500 — the guard working and the user seeing a
crash.

## What is deliberately different

| | Commons | Groups |
|---|---|---|
| Discovery | public feed | none — invitation only |
| Signal | upvotes, sorted | reactions, nothing sorted |
| Structure | posts + comments | channels + one level of threads |
| Deletion | moderation queue | tombstone in place |

**Reactions, not votes.** A vote ranks. Ranking a colleague's half-formed
thought changes what people are willing to say in a room, which is the whole
reason the room exists.

**Membership is explicit.** Invitations are by email and stay pending until
accepted, so a group's member list is never a list of people who did not agree
to be in it. There is no join-by-link and no public listing.

**Not a member and not a group are answered identically** — 404 for both.
"That group exists but you cannot see it" discloses the thing a private space
is for withholding.

**One level of threading.** A reply to a reply joins the same thread rather than
starting a nested one. Deep trees are where discussions go to become unreadable.

**Deletion leaves a tombstone.** A thread that silently loses a message reads as
though it never had one, and in a discussion of evidence that is its own kind of
falsification. The row stays, the reply count stays correct, only the body goes.

## Roles

`owner > moderator > member > reader`, checked by rank so a route needing
`member` also accepts a moderator. Owners invite and set roles; moderators pin
and remove any message; members write; readers only read. A group cannot be left
without an owner.

## Real-time

**Server-sent events, not WebSocket.** The stream is one-way — the client
already sends over HTTP — so SSE gets automatic reconnection, survives proxies
that mangle upgrade headers, and adds no second protocol to the deployment. A
WebSocket here would be a second connection lifecycle to get wrong in exchange
for a direction of travel nothing uses.

**Events carry ids, not bodies.** A client that receives an id re-fetches
through the same authorised endpoint as everything else, so the membership check
and the scripture guard are never on a path the stream could bypass.

**Fan-out is in-process, and this is a real limitation.** Listeners are held in
the worker process, so live push reaches only clients connected to the same
worker. Polling returns correct data everywhere; only the push is process-local.
A multi-worker deployment needs a shared bus before this is true real-time
across all of them. `GET /groups/meta` reports this so it cannot be mistaken —
the honest version of a limitation is a stated one.

A slow listener is dropped rather than allowed to apply backpressure to the
writer; it resyncs on reconnect. Heartbeat comments every 25 seconds keep
intermediaries from timing the connection out, and `x-accel-buffering: no` stops
nginx turning a live stream into a batch.

## Testing note

`EventSource` keeps a connection open, so Playwright's `networkidle` never
fires on this page. Use `domcontentloaded` plus an explicit wait.
