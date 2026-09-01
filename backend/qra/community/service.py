"""Community service: posts, comments, votes, flags, moderation.

The rule that matters here is the same one that governs agent output, applied
at the one place a human can type directly into the corpus's public surface:

    **Scripture is rendered from the database, never typed.**

A post body is a template. ``{{ayah:2:255}}`` is resolved against the corpus at
write time and its citation stored; raw Arabic that arrived through no
placeholder and appears in no corpus row is a write-time rejection, not a
warning. This is not pedantry — a feed over a religious corpus is precisely
where a fabricated verse would enter, and it would then carry the site's
authority and be screenshotted forever.

When the guard fires we do the work of fixing it: :func:`suggest_reference`
looks the offending run up in the corpus and, if it is genuinely scripture,
hands back the placeholder the author should have used.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from qra.agents.render import PLACEHOLDER_RE, render
from qra.models import (
    Ayah,
    Comment,
    Finding,
    Flag,
    Hypothesis,
    HypothesisRun,
    Note,
    Post,
    User,
    Vote,
)
from qra.security.auth import Principal

# `[[2:255]]` in a body is the same anchor syntax the notebook uses. Authors
# should not have to learn a second one.
ANCHOR_RE = re.compile(r"\[\[(\d{1,3}):(\d{1,3})\]\]")
ROOT_ANCHOR_RE = re.compile(r"\[\[root:([^\]]+)\]\]")

KINDS = ("question", "insight", "finding", "hypothesis", "correction")
FLAG_REASONS = (
    "fabricated_scripture",
    "misattribution",
    "off_topic",
    "abuse",
    "other",
)
SORTS = ("new", "useful", "evidence", "discussed")

# Beyond this many open flags a post is hidden automatically, pending review.
# Posting is immediate, so this is the only thing standing between a bad post
# and an unattended weekend.
AUTO_HIDE_FLAGS = 4

MAX_TITLE = 300
MAX_BODY = 20_000

# The reference lookup slides a shrinking window, which is quadratic in the
# passage length. Someone pasting 500 Arabic words would otherwise buy 125,000
# phrase searches for the price of one request, so both ends are capped: a
# suggestion is a courtesy, and a courtesy is not worth a denial of service.
MAX_SPAN_WORDS = 25
MAX_LOOKUPS = 40


class CommunityError(ValueError):
    """A write was refused. Carries what to fix, not just that it failed."""

    def __init__(self, message: str, *, violations: list[str] | None = None,
                 suggestions: list[dict] | None = None):
        super().__init__(message)
        self.violations = violations or []
        self.suggestions = suggestions or []


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


# A maximal stretch of Arabic-script words, which is what an author actually
# pasted. The scripture guard reports offending *words*; for suggesting a
# reference we need the passage they came from, because a single word like
# بِٱلصَّبْرِ appears in three unrelated ayat while the phrase appears in one.
ARABIC_SPAN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\s]{8,}")


def arabic_spans(text: str, *, min_words: int = 3) -> list[str]:
    """Contiguous Arabic passages in a body, longest first."""
    stripped = PLACEHOLDER_RE.sub(" ", text)
    spans = []
    for match in ARABIC_SPAN_RE.finditer(stripped):
        span = " ".join(match.group(0).split())
        if len(span.split()) >= min_words:
            spans.append(span)
    return sorted(set(spans), key=len, reverse=True)


def suggest_reference(session: Session, passage: str) -> dict | None:
    """Look an un-cited Arabic passage up in the corpus and name its placeholder.

    The guard's job is to refuse; this function's job is to make the refusal
    actionable. If the author really did paste 2:255, we can say so and hand
    back ``{{ayah:2:255}}`` rather than leaving them to guess what the rule
    wants. If it is *not* in the corpus, no suggestion comes back — and that
    silence is itself the finding, because it means the text was invented.
    """
    from qra.retrieval import deterministic as det

    words = passage.split()
    if not words:
        return None

    def look(phrase: str):
        try:
            return det.search_phrase(session, phrase, limit=3)
        except Exception:  # noqa: BLE001 - a lookup failure must not mask the refusal
            return None

    # Longest window first, shrinking to three words. The whole passage often
    # fails to match outright — an author pastes from a site with different
    # orthography, or quotes half a verse — and refusing to help in that case
    # would be the guard being right and useless at the same time. Three words
    # is the floor because below it a match says nothing: single Qur'anic words
    # recur across dozens of unrelated ayat.
    budget = MAX_LOOKUPS
    for size in range(min(len(words), MAX_SPAN_WORDS), 2, -1):
        for start in range(0, len(words) - size + 1):
            if budget <= 0:
                return None
            budget -= 1
            window = " ".join(words[start : start + size])
            result = look(window)
            if result and result.hits:
                hit = result.hits[0]
                return {
                    "passage": window[:120],
                    "partial": size < len(words),
                    "ref": hit.ref,
                    "placeholder": f"{{{{ayah:{hit.ref}}}}}",
                    "total_occurrences": result.total_occurrences,
                    "also_at": [h.ref for h in result.hits[1:]],
                }
    return None


def _prepare_body(session: Session, body: str) -> tuple[str, list[dict]]:
    """Render placeholders and refuse un-cited scripture. One door for both."""
    if len(body) > MAX_BODY:
        raise CommunityError(f"body is longer than {MAX_BODY:,} characters")

    rendered = render(session, body, strict=True)
    if rendered.violations:
        suggestions = [
            found
            for found in (suggest_reference(session, span) for span in arabic_spans(body))
            if found
        ]
        raise CommunityError(
            "This post contains Arabic that did not come from the corpus. "
            "Quote scripture by reference — the editor's 'insert ayah' button "
            "writes the placeholder for you — so every quotation on this site is "
            "the database's text rather than a retyping of it.",
            violations=rendered.violations,
            suggestions=suggestions,
        )
    return rendered.text, rendered.citations


def _anchors(body: str) -> tuple[list[int], list[str]]:
    """Ayah ids and roots this post is about, from both anchor syntaxes."""
    ayah_ids: list[int] = []
    for surah, ayah in ANCHOR_RE.findall(body):
        ayah_ids.append(_ayah_key(int(surah), int(ayah)))
    for match in PLACEHOLDER_RE.finditer(body):
        ref = match.group("ref").strip()
        if ":" in ref and match.group("kind") in ("ayah", "translation", "tafsir"):
            try:
                surah, ayah = ref.split(":", 1)
                ayah_ids.append(_ayah_key(int(surah), int(ayah)))
            except ValueError:
                continue
    roots = [r.strip() for r in ROOT_ANCHOR_RE.findall(body) if r.strip()]
    return sorted(set(ayah_ids)), sorted(set(roots))


def _ayah_key(surah: int, ayah: int) -> int:
    """Encoded surah:ayah. Resolved to a real id at read time if it exists."""
    return surah * 1000 + ayah


def _resolve_ayah_ids(session: Session, keys: list[int]) -> list[int]:
    if not keys:
        return []
    pairs = [(k // 1000, k % 1000) for k in keys]
    rows = session.execute(
        select(Ayah.id, Ayah.surah_id, Ayah.ayah_num).where(
            Ayah.surah_id.in_([s for s, _ in pairs])
        )
    ).all()
    index = {(surah, number): ayah_id for ayah_id, surah, number in rows}
    return [index[pair] for pair in pairs if pair in index]


def create_post(
    session: Session,
    *,
    principal: Principal,
    title: str,
    body: str,
    language: str = "en",
    kind: str = "insight",
    finding_id: int | None = None,
    hypothesis_id: int | None = None,
    note_id: int | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    title = (title or "").strip()
    if not title:
        raise CommunityError("a post needs a title")
    if len(title) > MAX_TITLE:
        raise CommunityError(f"title is longer than {MAX_TITLE} characters")
    if kind not in KINDS:
        raise CommunityError(f"unknown post kind {kind!r} (expected one of {', '.join(KINDS)})")

    body_rendered, citations = _prepare_body(session, body)
    ayah_keys, roots = _anchors(body)

    attachment = _validate_attachment(
        session,
        principal=principal,
        finding_id=finding_id,
        hypothesis_id=hypothesis_id,
        note_id=note_id,
    )

    post = Post(
        author_id=principal.user_id,
        org_id=principal.org_id,
        title=title,
        body=body,
        body_rendered=body_rendered,
        language=language,
        kind=kind,
        finding_id=finding_id,
        hypothesis_id=hypothesis_id,
        note_id=note_id,
        run_id=run_id,
        ayah_ids=_resolve_ayah_ids(session, ayah_keys) or attachment.get("ayah_ids", []),
        roots=roots,
        tags=[t.strip() for t in (tags or []) if t.strip()][:8],
        citations=citations,
    )
    session.add(post)
    session.commit()
    session.refresh(post)
    return post_to_dict(session, post, principal=principal)


def _validate_attachment(
    session: Session,
    *,
    principal: Principal,
    finding_id: int | None,
    hypothesis_id: int | None,
    note_id: int | None,
) -> dict:
    """You may only attach your own work, or a finding a reviewer approved.

    Without this, a post could borrow the authority of someone else's verified
    finding — which is the one thing the evidence badge is supposed to mean.
    """
    if finding_id is not None:
        finding = session.get(Finding, finding_id)
        if finding is None:
            raise CommunityError(f"finding {finding_id} not found")
        if finding.author_id != principal.user_id and finding.review_status != "approved":
            raise CommunityError(
                "you can attach your own findings, or any finding a reviewer has approved"
            )
        return {"ayah_ids": list(finding.ayah_ids or [])}

    if hypothesis_id is not None:
        hypothesis = session.get(Hypothesis, hypothesis_id)
        if hypothesis is None:
            raise CommunityError(f"hypothesis {hypothesis_id} not found")
        if hypothesis.author_id != principal.user_id:
            raise CommunityError("you can only attach your own hypotheses")

    if note_id is not None:
        note = session.get(Note, note_id)
        if note is None:
            raise CommunityError(f"note {note_id} not found")
        if note.author_id != principal.user_id:
            raise CommunityError("you can only attach your own notes")

    return {}


def edit_post(
    session: Session, post_id: int, *, principal: Principal, title: str | None = None,
    body: str | None = None, tags: list[str] | None = None,
) -> dict | None:
    post = session.get(Post, post_id)
    if post is None:
        return None
    if post.author_id != principal.user_id and not principal.has_role("reviewer"):
        raise CommunityError("only the author can edit this post")
    if title is not None:
        post.title = title.strip()[:MAX_TITLE]
    if body is not None:
        post.body_rendered, post.citations = _prepare_body(session, body)
        post.body = body
        keys, roots = _anchors(body)
        post.ayah_ids = _resolve_ayah_ids(session, keys)
        post.roots = roots
    if tags is not None:
        post.tags = [t.strip() for t in tags if t.strip()][:8]
    post.edited_at = datetime.now(UTC)
    session.commit()
    return post_to_dict(session, post, principal=principal)


def add_comment(
    session: Session,
    post_id: int,
    *,
    principal: Principal,
    body: str,
    parent_id: int | None = None,
    language: str = "en",
) -> dict:
    post = session.get(Post, post_id)
    if post is None or post.status != "visible":
        raise CommunityError("that post is not open for comment")
    if parent_id is not None:
        parent = session.get(Comment, parent_id)
        if parent is None or parent.post_id != post_id:
            raise CommunityError("that reply target does not belong to this post")
        # One level of nesting. Deeper threads on a scholarly claim fragment the
        # argument into branches nobody reads to the end of.
        parent_id = parent.parent_id or parent.id

    body_rendered, citations = _prepare_body(session, body)
    comment = Comment(
        post_id=post_id,
        parent_id=parent_id,
        author_id=principal.user_id,
        body=body,
        body_rendered=body_rendered,
        language=language,
        citations=citations,
    )
    session.add(comment)
    session.flush()
    post.comment_count = _count_comments(session, post_id)
    session.commit()
    session.refresh(comment)
    return comment_to_dict(session, comment, principal=principal)


def _count_comments(session: Session, post_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Comment)
            .where(Comment.post_id == post_id, Comment.status == "visible")
        )
        or 0
    )


# --------------------------------------------------------------------------
# signals
# --------------------------------------------------------------------------


def toggle_vote(
    session: Session, *, target_kind: str, target_id: int, principal: Principal
) -> dict:
    """Upvote or take it back. There is no downvote — see :class:`Vote`."""
    if target_kind not in ("post", "comment"):
        raise CommunityError("you can only vote on a post or a comment")
    model = Post if target_kind == "post" else Comment
    target = session.get(model, target_id)
    if target is None:
        raise CommunityError(f"{target_kind} {target_id} not found")
    if target.author_id == principal.user_id:
        raise CommunityError("you cannot upvote your own post")

    existing = session.scalar(
        select(Vote).where(
            Vote.target_kind == target_kind,
            Vote.target_id == target_id,
            Vote.user_id == principal.user_id,
        )
    )
    if existing is not None:
        session.delete(existing)
        voted = False
    else:
        session.add(
            Vote(target_kind=target_kind, target_id=target_id, user_id=principal.user_id)
        )
        voted = True
    session.flush()

    total = (
        session.scalar(
            select(func.count())
            .select_from(Vote)
            .where(Vote.target_kind == target_kind, Vote.target_id == target_id)
        )
        or 0
    )
    target.upvotes = total
    session.commit()
    return {"target_kind": target_kind, "target_id": target_id, "upvotes": total, "voted": voted}


def _voted_ids(
    session: Session, target_kind: str, ids: list[int], principal: Principal | None
) -> set[int]:
    if not ids or principal is None or not principal.user_id:
        return set()
    rows = session.execute(
        select(Vote.target_id).where(
            Vote.target_kind == target_kind,
            Vote.target_id.in_(ids),
            Vote.user_id == principal.user_id,
        )
    ).all()
    return {row[0] for row in rows}


# --------------------------------------------------------------------------
# moderation
# --------------------------------------------------------------------------


def flag(
    session: Session,
    *,
    target_kind: str,
    target_id: int,
    principal: Principal,
    reason: str,
    detail: str | None = None,
) -> dict:
    if reason not in FLAG_REASONS:
        raise CommunityError(f"unknown reason {reason!r}")
    model = Post if target_kind == "post" else Comment
    target = session.get(model, target_id)
    if target is None:
        raise CommunityError(f"{target_kind} {target_id} not found")

    already = session.scalar(
        select(Flag).where(
            Flag.target_kind == target_kind,
            Flag.target_id == target_id,
            Flag.reporter_id == principal.user_id,
        )
    )
    if already is not None:
        return {"flagged": True, "already": True, "flag_id": already.id}

    session.add(
        Flag(
            target_kind=target_kind,
            target_id=target_id,
            reporter_id=principal.user_id,
            reason=reason,
            detail=detail,
        )
    )
    session.flush()
    open_flags = (
        session.scalar(
            select(func.count())
            .select_from(Flag)
            .where(
                Flag.target_kind == target_kind,
                Flag.target_id == target_id,
                Flag.resolution == "open",
            )
        )
        or 0
    )
    target.flag_count = open_flags

    auto_hidden = False
    if open_flags >= AUTO_HIDE_FLAGS and target.status == "visible":
        # Hidden, not removed: a reviewer still has to decide, and the row and
        # its history stay intact either way.
        target.status = "hidden"
        target.moderation_reason = (
            f"automatically hidden after {open_flags} open flags, pending review"
        )
        target.moderated_at = datetime.now(UTC)
        auto_hidden = True

    session.commit()
    return {
        "flagged": True,
        "open_flags": open_flags,
        "auto_hidden": auto_hidden,
        "threshold": AUTO_HIDE_FLAGS,
    }


def flag_queue(session: Session, *, resolution: str = "open", limit: int = 50) -> list[dict]:
    rows = session.scalars(
        select(Flag).where(Flag.resolution == resolution).order_by(Flag.created_at.desc()).limit(limit)
    ).all()
    out = []
    for row in rows:
        model = Post if row.target_kind == "post" else Comment
        target = session.get(model, row.target_id)
        out.append(
            {
                "id": row.id,
                "target_kind": row.target_kind,
                "target_id": row.target_id,
                "reason": row.reason,
                "detail": row.detail,
                "resolution": row.resolution,
                "created_at": row.created_at.isoformat(),
                "target": {
                    "title": getattr(target, "title", None),
                    "excerpt": (getattr(target, "body_rendered", "") or "")[:400],
                    "status": getattr(target, "status", "missing"),
                    "author_id": getattr(target, "author_id", None),
                }
                if target is not None
                else None,
            }
        )
    return out


def moderate(
    session: Session,
    *,
    target_kind: str,
    target_id: int,
    principal: Principal,
    action: str,
    reason: str,
) -> dict:
    """Reviewer action. The reason is required and stored — a removal nobody
    can account for later is indistinguishable from censorship."""
    if action not in ("hide", "remove", "restore"):
        raise CommunityError(f"unknown action {action!r}")
    if not (reason or "").strip():
        raise CommunityError("moderation requires a reason, which is recorded on the post")

    model = Post if target_kind == "post" else Comment
    target = session.get(model, target_id)
    if target is None:
        raise CommunityError(f"{target_kind} {target_id} not found")

    target.status = {"hide": "hidden", "remove": "removed", "restore": "visible"}[action]
    target.moderated_by = principal.user_id
    target.moderation_reason = reason.strip()
    if hasattr(target, "moderated_at"):
        target.moderated_at = datetime.now(UTC)

    session.execute(
        update(Flag)
        .where(
            Flag.target_kind == target_kind,
            Flag.target_id == target_id,
            Flag.resolution == "open",
        )
        .values(
            resolution="dismissed" if action == "restore" else "upheld",
            resolved_by=principal.user_id,
            resolved_at=datetime.now(UTC),
            resolution_notes=reason.strip(),
        )
    )
    target.flag_count = 0
    if target_kind == "comment":
        post = session.get(Post, target.post_id)
        if post is not None:
            post.comment_count = _count_comments(session, target.post_id)
    session.commit()
    return {
        "target_kind": target_kind,
        "target_id": target_id,
        "status": target.status,
        "reason": target.moderation_reason,
    }


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def feed(
    session: Session,
    *,
    principal: Principal | None = None,
    sort: str = "new",
    kind: str | None = None,
    tag: str | None = None,
    author_id: int | None = None,
    ayah_id: int | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """A page of the feed.

    Always ``exhaustive: false``. Every ordering here is a judgement — recency,
    popularity, how much evidence is attached — and the app is consistent about
    saying so: only deterministic corpus retrieval claims completeness.
    """
    if sort not in SORTS:
        sort = "new"

    stmt = select(Post).where(Post.status == "visible")
    if kind:
        stmt = stmt.where(Post.kind == kind)
    if author_id:
        stmt = stmt.where(Post.author_id == author_id)
    if tag:
        stmt = stmt.where(Post.tags.contains([tag]))
    if ayah_id:
        stmt = stmt.where(Post.ayah_ids.contains([ayah_id]))
    if sort == "evidence":
        # Posts carrying something checkable, newest first. Not a quality
        # ranking — an attachment means "this can be verified", not "this is
        # right".
        stmt = stmt.where(
            (Post.finding_id.is_not(None))
            | (Post.hypothesis_id.is_not(None))
            | (Post.note_id.is_not(None))
        )

    total = session.scalar(
        select(func.count()).select_from(stmt.subquery())
    ) or 0

    order = {
        "new": Post.created_at.desc(),
        "useful": Post.upvotes.desc(),
        "discussed": Post.comment_count.desc(),
        "evidence": Post.created_at.desc(),
    }[sort]
    # Recency always breaks ties, so an old post cannot sit at the top of
    # "useful" forever on a handful of early votes.
    rows = session.scalars(
        stmt.order_by(order, Post.created_at.desc()).limit(limit).offset(offset)
    ).all()

    voted = _voted_ids(session, "post", [p.id for p in rows], principal)
    return {
        "sort": sort,
        "total": total,
        "limit": limit,
        "offset": offset,
        "exhaustive": False,
        "note": (
            "The feed is ranked, not exhaustive. Upvotes measure how many people "
            "found a post useful — never whether it is correct. Where a post "
            "attaches evidence, that evidence is shown beside the score and is "
            "not affected by it."
        ),
        "posts": [
            post_to_dict(session, post, principal=principal, voted=post.id in voted, brief=True)
            for post in rows
        ],
    }


def get_post(session: Session, post_id: int, *, principal: Principal | None = None) -> dict | None:
    post = session.get(Post, post_id)
    if post is None:
        return None
    if post.status != "visible" and not (
        principal and (principal.has_role("reviewer") or post.author_id == principal.user_id)
    ):
        # The row survives moderation; the content does not resurface.
        return {
            "id": post.id,
            "status": post.status,
            "removed": True,
            "moderation_reason": post.moderation_reason,
            "note": "This post was removed by a reviewer. The reason is recorded above.",
        }
    payload = post_to_dict(session, post, principal=principal)
    payload["comments"] = comment_tree(session, post_id, principal=principal)
    return payload


def comment_tree(
    session: Session, post_id: int, *, principal: Principal | None = None
) -> list[dict]:
    rows = session.scalars(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at.asc())
    ).all()
    voted = _voted_ids(session, "comment", [c.id for c in rows], principal)

    by_parent: dict[int | None, list[Comment]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)

    def build(parent: int | None) -> list[dict]:
        out = []
        for row in by_parent.get(parent, []):
            payload = comment_to_dict(session, row, principal=principal, voted=row.id in voted)
            payload["replies"] = build(row.id)
            out.append(payload)
        return out

    return build(None)


def posts_for_ayah(session: Session, surah: int, ayah: int, limit: int = 10) -> list[dict]:
    """Discussion anchored to one ayah — the reader's backlink panel."""
    row = session.scalar(
        select(Ayah.id).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
    )
    if row is None:
        return []
    posts = session.scalars(
        select(Post)
        .where(Post.status == "visible", Post.ayah_ids.contains([row]))
        .order_by(Post.upvotes.desc(), Post.created_at.desc())
        .limit(limit)
    ).all()
    return [post_to_dict(session, post, brief=True) for post in posts]


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------


def _author(session: Session, user_id: int | None) -> dict:
    if not user_id:
        return {"id": None, "display_name": "unknown", "role": None}
    user = session.get(User, user_id)
    if user is None:
        return {"id": user_id, "display_name": "deleted account", "role": None}
    # Email is never serialised into the feed. Display name and role are what a
    # reader needs to weigh a post; the address is not theirs to have.
    return {"id": user.id, "display_name": user.display_name, "role": user.role}


def evidence_for(session: Session, post: Post) -> dict | None:
    """The checkable object behind a post, if it has one.

    A hypothesis attachment reports its *verdict*, including when that verdict
    is "refuted". That is the whole point: the score says how many people liked
    the post, and this says what the corpus actually returned. They are allowed
    to disagree, and when they do the reader sees both.
    """
    if post.finding_id:
        finding = session.get(Finding, post.finding_id)
        if finding is None:
            return None
        return {
            "kind": "finding",
            "id": finding.id,
            "question": finding.question,
            "summary": finding.summary[:600],
            "review_status": finding.review_status,
            "citation_count": len(finding.citations or []),
            "run_id": finding.run_id,
            "verified": finding.review_status == "approved",
        }

    if post.hypothesis_id:
        hypothesis = session.get(Hypothesis, post.hypothesis_id)
        if hypothesis is None:
            return None
        latest = session.scalar(
            select(HypothesisRun)
            .where(HypothesisRun.hypothesis_id == hypothesis.id)
            .order_by(HypothesisRun.created_at.desc())
            .limit(1)
        )
        result: dict[str, Any] = {
            "kind": "hypothesis",
            "id": hypothesis.id,
            "title": hypothesis.title,
            "statement": hypothesis.statement,
            "status": hypothesis.status,
            "verified": latest is not None,
        }
        if latest is not None:
            result |= {
                "verdict": latest.verdict,
                "violating_count": len(latest.violating or []),
                "supporting_count": len(latest.supporting or []),
                "coverage": latest.coverage,
                "within_chance": (latest.statistics or {}).get("within_chance"),
                "tested_at": latest.created_at.isoformat(),
            }
        return result

    if post.note_id:
        note = session.get(Note, post.note_id)
        if note is None:
            return None
        return {
            "kind": "note",
            "id": note.id,
            "title": note.title,
            "provenance": note.provenance,
            "anchors": [a.ref for a in note.anchors if a.ref],
            "verified": False,
        }

    return None


def post_to_dict(
    session: Session,
    post: Post,
    *,
    principal: Principal | None = None,
    voted: bool | None = None,
    brief: bool = False,
) -> dict:
    if voted is None and principal is not None and principal.user_id:
        voted = bool(
            session.scalar(
                select(Vote.id).where(
                    Vote.target_kind == "post",
                    Vote.target_id == post.id,
                    Vote.user_id == principal.user_id,
                )
            )
        )
    evidence = evidence_for(session, post)
    body = post.body_rendered or post.body
    return {
        "id": post.id,
        "kind": post.kind,
        "title": post.title,
        "body": body[:600] + ("…" if brief and len(body) > 600 else "") if brief else body,
        "body_template": None if brief else post.body,
        "language": post.language,
        "author": _author(session, post.author_id),
        "tags": post.tags or [],
        "ayah_ids": post.ayah_ids or [],
        "roots": post.roots or [],
        "citations": post.citations or [],
        "citation_count": len(post.citations or []),
        "evidence": evidence,
        "has_evidence": evidence is not None,
        "upvotes": post.upvotes,
        "voted": bool(voted),
        "comment_count": post.comment_count,
        "status": post.status,
        "flag_count": post.flag_count,
        "created_at": post.created_at.isoformat(),
        "edited_at": post.edited_at.isoformat() if post.edited_at else None,
        "can_edit": bool(principal and principal.user_id == post.author_id),
    }


def comment_to_dict(
    session: Session,
    comment: Comment,
    *,
    principal: Principal | None = None,
    voted: bool | None = None,
) -> dict:
    removed = comment.status != "visible"
    if voted is None and principal is not None and principal.user_id:
        voted = bool(
            session.scalar(
                select(Vote.id).where(
                    Vote.target_kind == "comment",
                    Vote.target_id == comment.id,
                    Vote.user_id == principal.user_id,
                )
            )
        )
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "parent_id": comment.parent_id,
        "author": _author(session, comment.author_id),
        "body": (
            f"[removed by a reviewer: {comment.moderation_reason or 'no reason recorded'}]"
            if removed
            else (comment.body_rendered or comment.body)
        ),
        "language": comment.language,
        "citations": [] if removed else (comment.citations or []),
        "upvotes": comment.upvotes,
        "voted": bool(voted),
        "status": comment.status,
        "removed": removed,
        "created_at": comment.created_at.isoformat(),
        "can_edit": bool(principal and principal.user_id == comment.author_id and not removed),
    }


def stats(session: Session) -> dict:
    return {
        "posts": session.scalar(
            select(func.count()).select_from(Post).where(Post.status == "visible")
        )
        or 0,
        "with_evidence": session.scalar(
            select(func.count())
            .select_from(Post)
            .where(
                Post.status == "visible",
                (Post.finding_id.is_not(None))
                | (Post.hypothesis_id.is_not(None))
                | (Post.note_id.is_not(None)),
            )
        )
        or 0,
        "comments": session.scalar(
            select(func.count()).select_from(Comment).where(Comment.status == "visible")
        )
        or 0,
        "open_flags": session.scalar(
            select(func.count()).select_from(Flag).where(Flag.resolution == "open")
        )
        or 0,
    }
