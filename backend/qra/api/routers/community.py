"""The commons: shared research, discussion and signals.

Role gates follow the rest of the app — `reader` to read, `researcher` to write,
`reviewer` to moderate — so the community layer cannot become a softer path into
the system than the workspace it sits on.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from qra.api.deps import needs
from qra.community import service
from qra.community.service import CommunityError
from qra.db import get_session
from qra.ops import _limiter

router = APIRouter(prefix="/community", tags=["community"])


def _refuse(exc: CommunityError) -> HTTPException:
    """422 with the fix attached.

    When the scripture guard fires, the response carries the offending runs and,
    where the text really is in the corpus, the placeholder the author should
    have used. A refusal a writer cannot act on just teaches them to give up.
    """
    return HTTPException(
        422,
        detail={
            "message": str(exc),
            "violations": exc.violations,
            "suggestions": exc.suggestions,
        },
    )


def _throttle(principal, request: Request, cost: int = 1) -> None:
    """Writing is rate limited per principal; reading is not.

    Posting is immediate on this deployment, so the flood defence has to live
    here rather than in a moderation queue.
    """
    who = principal.user_id or (request.client.host if request.client else "anon")
    key = f"community:write:{who}"
    for _ in range(cost):
        allowed, retry_after = _limiter.check(key)
        if not allowed:
            raise HTTPException(
                429,
                "You are posting faster than the limit allows. This is a research "
                "commons, not a timeline — the limit clears within a minute.",
                headers={"retry-after": str(retry_after)},
            )


# --- reading ---------------------------------------------------------------


@router.get("/feed")
def get_feed(
    sort: str = "new",
    kind: str | None = None,
    tag: str | None = None,
    author_id: int | None = None,
    ayah_id: int | None = None,
    limit: int = 25,
    offset: int = 0,
    principal=needs("reader"),
    session: Session = Depends(get_session),
) -> dict:
    """Ranked, never exhaustive — the payload says so on every page."""
    return service.feed(
        session,
        principal=principal,
        sort=sort,
        kind=kind,
        tag=tag,
        author_id=author_id,
        ayah_id=ayah_id,
        limit=min(limit, 100),
        offset=offset,
    )


@router.get("/stats")
def get_stats(principal=needs("reader"), session: Session = Depends(get_session)) -> dict:
    return service.stats(session)


@router.get("/posts/{post_id}")
def read_post(
    post_id: int, principal=needs("reader"), session: Session = Depends(get_session)
) -> dict:
    payload = service.get_post(session, post_id, principal=principal)
    if payload is None:
        raise HTTPException(404, f"post {post_id} not found")
    return payload


@router.get("/ayah/{surah}/{ayah}")
def discussion_for_ayah(
    surah: int, ayah: int, principal=needs("reader"), session: Session = Depends(get_session)
) -> list[dict]:
    """Every post anchored to this ayah — the reader's discussion panel."""
    return service.posts_for_ayah(session, surah, ayah)


# --- writing ---------------------------------------------------------------


@router.post("/posts")
def create_post(
    request: Request,
    title: str = Body(...),
    body: str = Body(...),
    language: str = Body("en"),
    kind: str = Body("insight"),
    finding_id: int | None = Body(None),
    hypothesis_id: int | None = Body(None),
    note_id: int | None = Body(None),
    run_id: str | None = Body(None),
    tags: list[str] | None = Body(None),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Share something. Scripture must arrive as a placeholder, not as typed
    Arabic — the same rule the agents are held to."""
    _throttle(principal, request, cost=3)
    try:
        return service.create_post(
            session,
            principal=principal,
            title=title,
            body=body,
            language=language,
            kind=kind,
            finding_id=finding_id,
            hypothesis_id=hypothesis_id,
            note_id=note_id,
            run_id=run_id,
            tags=tags,
        )
    except CommunityError as exc:
        raise _refuse(exc) from exc


@router.patch("/posts/{post_id}")
def update_post(
    post_id: int,
    title: str | None = Body(None),
    body: str | None = Body(None),
    tags: list[str] | None = Body(None),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    try:
        payload = service.edit_post(
            session, post_id, principal=principal, title=title, body=body, tags=tags
        )
    except CommunityError as exc:
        raise _refuse(exc) from exc
    if payload is None:
        raise HTTPException(404, f"post {post_id} not found")
    return payload


@router.post("/posts/{post_id}/comments")
def create_comment(
    post_id: int,
    request: Request,
    body: str = Body(..., embed=True),
    parent_id: int | None = Body(None, embed=True),
    language: str = Body("en", embed=True),
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    _throttle(principal, request)
    try:
        return service.add_comment(
            session,
            post_id,
            principal=principal,
            body=body,
            parent_id=parent_id,
            language=language,
        )
    except CommunityError as exc:
        raise _refuse(exc) from exc


@router.post("/{target_kind}/{target_id}/vote")
def vote(
    target_kind: str,
    target_id: int,
    request: Request,
    principal=needs("researcher"),
    session: Session = Depends(get_session),
) -> dict:
    """Toggle an upvote. Upvote means "I found this useful", not "this is true" —
    which is why there is no downvote and why evidence is reported separately."""
    _throttle(principal, request)
    try:
        return service.toggle_vote(
            session, target_kind=target_kind, target_id=target_id, principal=principal
        )
    except CommunityError as exc:
        raise _refuse(exc) from exc


@router.post("/{target_kind}/{target_id}/flag")
def flag(
    target_kind: str,
    target_id: int,
    reason: str = Body(..., embed=True),
    detail: str | None = Body(None, embed=True),
    principal=needs("reader"),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return service.flag(
            session,
            target_kind=target_kind,
            target_id=target_id,
            principal=principal,
            reason=reason,
            detail=detail,
        )
    except CommunityError as exc:
        raise _refuse(exc) from exc


# --- moderation ------------------------------------------------------------


@router.get("/flags")
def flags(
    resolution: str = "open",
    principal=needs("reviewer"),
    session: Session = Depends(get_session),
) -> list[dict]:
    return service.flag_queue(session, resolution=resolution)


@router.post("/{target_kind}/{target_id}/moderate")
def moderate(
    target_kind: str,
    target_id: int,
    action: str = Body(..., embed=True),
    reason: str = Body(..., embed=True),
    principal=needs("reviewer"),
    session: Session = Depends(get_session),
) -> dict:
    """hide | remove | restore. The reason is mandatory and is stored on the row:
    a removal nobody can account for later is indistinguishable from censorship."""
    try:
        return service.moderate(
            session,
            target_kind=target_kind,
            target_id=target_id,
            principal=principal,
            action=action,
            reason=reason,
        )
    except CommunityError as exc:
        raise _refuse(exc) from exc
