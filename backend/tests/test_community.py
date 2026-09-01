"""The commons, and the one rule it must not weaken.

A feed is the only place on this site where a human types directly into a public
surface. If fabricated scripture can enter anywhere, it enters here — and it
would then carry the site's authority. So these tests are mostly about what the
community layer *refuses*.
"""

from __future__ import annotations

import pytest

from qra.community import service
from qra.community.service import CommunityError
from qra.security.auth import Principal

REAL_AYAH_2_45 = (
    "وَٱسْتَعِينُوا۟ بِٱلصَّبْرِ وَٱلصَّلَوٰةِ وَإِنَّهَا لَكَبِيرَةٌ إِلَّا عَلَى ٱلْخَٰشِعِينَ"
)
# Grammatical, plausible, and in no ayah. This is the failure mode that matters.
FABRICATED = "وَقَالَ ٱلرَّحْمَٰنُ إِنَّ ٱلْعِلْمَ نُورٌ وَٱلْجَهْلَ ظُلْمَةٌ فَٱتَّقُوا۟ رَبَّكُمْ"


def _principal(session, email: str, role: str = "researcher") -> Principal:
    from sqlalchemy import select

    from qra.models import User
    from qra.security.service import register_user

    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = register_user(session, email=email, password="pw-for-tests-1234", display_name=email.split("@")[0])
        user.role = role
        session.commit()
    return Principal(
        user_id=user.id,
        email=user.email,
        role=role,
        org_id=None,
        display_name=user.display_name,
        issuer="test",
    )


@pytest.fixture
def author(session):
    return _principal(session, "community-author@example.org")


@pytest.fixture
def reader(session):
    return _principal(session, "community-reader@example.org")


# --- the scripture guard ---------------------------------------------------


def test_a_post_may_quote_by_reference(session, author):
    post = service.create_post(
        session,
        principal=author,
        title="Quoting by reference",
        body="The pairing is explicit: {{ayah:2:45}}",
    )
    assert post["citation_count"] == 1
    # The Arabic in the stored body came out of the database, not the request.
    assert "ٱلۡخَٰشِعِينَ" in post["body"] or "الخاشعين" in post["body"]
    assert post["citations"][0]["ref"] == "2:45"


def test_pasting_a_real_ayah_is_refused_but_helped(session, author):
    """Refusing is half the job; naming the reference is the other half."""
    with pytest.raises(CommunityError) as excinfo:
        service.create_post(
            session, principal=author, title="pasted", body=f"Look: {REAL_AYAH_2_45}"
        )
    suggestions = excinfo.value.suggestions
    assert suggestions, "the guard refused without telling the author what to do instead"
    assert suggestions[0]["ref"] == "2:45"
    assert suggestions[0]["placeholder"] == "{{ayah:2:45}}"


def test_fabricated_scripture_is_refused_with_no_reference(session, author):
    """The absence of a suggestion is the finding: this text is in no ayah."""
    with pytest.raises(CommunityError) as excinfo:
        service.create_post(
            session, principal=author, title="fabricated", body=f"As it says: {FABRICATED}"
        )
    assert excinfo.value.suggestions == []
    assert excinfo.value.violations


def test_urdu_prose_is_not_mistaken_for_scripture(session, author):
    post = service.create_post(
        session,
        principal=author,
        title="ایک خیال",
        body="یہ صرف ایک خیال ہے، کوئی آیت نہیں۔ صبر کے بارے میں سوچ رہا ہوں۔",
        language="ur",
        kind="question",
    )
    assert post["id"]


def test_the_guard_applies_to_comments_too(session, author):
    """A comment box is not a softer path into the corpus than a post box."""
    post = service.create_post(
        session, principal=author, title="host post", body="A question about patience."
    )
    with pytest.raises(CommunityError):
        service.add_comment(
            session, post["id"], principal=author, body=f"But see: {FABRICATED}"
        )


def test_the_suggestion_lookup_is_bounded(session, author):
    """A long paste must not buy thousands of phrase searches for one request."""
    import time

    huge = " ".join([REAL_AYAH_2_45] * 30)
    started = time.perf_counter()
    with pytest.raises(CommunityError):
        service.create_post(session, principal=author, title="huge", body=huge)
    assert time.perf_counter() - started < 15


# --- signals ---------------------------------------------------------------


def test_you_cannot_upvote_your_own_post(session, author):
    post = service.create_post(session, principal=author, title="mine", body="a thought")
    with pytest.raises(CommunityError):
        service.toggle_vote(
            session, target_kind="post", target_id=post["id"], principal=author
        )


def test_voting_is_a_toggle_and_counted_once(session, author, reader):
    post = service.create_post(session, principal=author, title="votable", body="a thought")
    first = service.toggle_vote(
        session, target_kind="post", target_id=post["id"], principal=reader
    )
    assert first["voted"] is True and first["upvotes"] == 1

    again = service.toggle_vote(
        session, target_kind="post", target_id=post["id"], principal=reader
    )
    assert again["voted"] is False and again["upvotes"] == 0


def test_there_is_no_downvote(session):
    """Not an omission. A downvote on a scholarly claim is a popularity verdict
    wearing the costume of a correctness verdict."""
    import inspect

    source = inspect.getsource(service)
    assert "downvote" not in source.lower().replace("no downvote", "").replace(
        "there is no downvote", ""
    )


# --- evidence vs popularity ------------------------------------------------


def test_a_refuted_hypothesis_stays_refuted_however_popular(session, author, reader):
    """The core rule of this layer: votes never overwrite evidence."""
    from qra.models import Hypothesis, HypothesisRun

    hypothesis = Hypothesis(
        author_id=author.user_id,
        title="Sabr always accompanies salah",
        statement="Quran mein sabr hamesha salah ke saath aata hai",
        language="ur",
        status="refuted",
    )
    session.add(hypothesis)
    session.flush()
    session.add(
        HypothesisRun(
            hypothesis_id=hypothesis.id,
            verdict="refuted",
            violating=[1, 2, 3, 4],
            supporting=[5],
            coverage=0.2,
            statistics={"within_chance": True},
        )
    )
    session.commit()

    post = service.create_post(
        session,
        principal=author,
        title="I think sabr always comes with salah",
        body="Posting my hypothesis for discussion.",
        kind="hypothesis",
        hypothesis_id=hypothesis.id,
    )
    for voter_email in ("v1@example.org", "v2@example.org", "v3@example.org"):
        service.toggle_vote(
            session,
            target_kind="post",
            target_id=post["id"],
            principal=_principal(session, voter_email),
        )

    payload = service.get_post(session, post["id"], principal=reader)
    assert payload["upvotes"] == 3
    assert payload["evidence"]["verdict"] == "refuted"
    assert payload["evidence"]["violating_count"] == 4


def test_you_cannot_borrow_someone_elses_unapproved_finding(session, author, reader):
    """The evidence badge has to mean something, so attachments are owned."""
    from qra.models import Finding

    finding = Finding(
        author_id=author.user_id,
        question="q",
        summary="s",
        fingerprint="fp-community-test",
        review_status="draft",
    )
    session.add(finding)
    session.commit()

    with pytest.raises(CommunityError):
        service.create_post(
            session,
            principal=reader,
            title="borrowed",
            body="not mine",
            finding_id=finding.id,
        )


# --- the feed --------------------------------------------------------------


def test_the_feed_never_claims_to_be_exhaustive(session, author):
    payload = service.feed(session, principal=author)
    assert payload["exhaustive"] is False
    assert "ranked" in payload["note"].lower()
    assert "useful" in payload["note"].lower()


# --- moderation ------------------------------------------------------------


def test_moderation_requires_a_recorded_reason(session, author):
    post = service.create_post(session, principal=author, title="to moderate", body="text")
    reviewer = _principal(session, "community-reviewer@example.org", role="reviewer")
    with pytest.raises(CommunityError):
        service.moderate(
            session,
            target_kind="post",
            target_id=post["id"],
            principal=reviewer,
            action="remove",
            reason="   ",
        )


def test_a_removed_post_keeps_its_row_and_shows_the_reason(session, author, reader):
    """Moderation has to be auditable, so removal hides content without
    destroying the record of what was removed and why."""
    post = service.create_post(session, principal=author, title="bad post", body="text")
    reviewer = _principal(session, "community-reviewer@example.org", role="reviewer")
    service.moderate(
        session,
        target_kind="post",
        target_id=post["id"],
        principal=reviewer,
        action="remove",
        reason="misattributed a hadith grading",
    )
    seen = service.get_post(session, post["id"], principal=reader)
    assert seen["removed"] is True
    assert "misattributed" in seen["moderation_reason"]
    assert "body" not in seen

    feed = service.feed(session, principal=reader)
    assert post["id"] not in [p["id"] for p in feed["posts"]]


def test_enough_flags_hide_a_post_pending_review(session, author):
    post = service.create_post(session, principal=author, title="flagged", body="text")
    result = {}
    for index in range(service.AUTO_HIDE_FLAGS):
        result = service.flag(
            session,
            target_kind="post",
            target_id=post["id"],
            principal=_principal(session, f"flagger{index}@example.org"),
            reason="fabricated_scripture",
        )
    assert result["auto_hidden"] is True


def test_writing_works_with_auth_disabled(session, monkeypatch):
    """Running open is a supported mode, so the local identity needs a real row.

    ``bootstrap_principal`` carries ``user_id=0``, which is a sentinel and not a
    row in ``app_user``. Every authored write — a note, a finding, a post —
    carries a foreign key to that table, so without resolving the sentinel the
    whole app is read-only the moment auth is switched off, which is the default
    for a laptop.
    """
    from qra.security.service import LOCAL_EMAIL, local_user

    user = local_user(session)
    assert user.id and user.email == LOCAL_EMAIL
    # Idempotent: a second call must not create a second local account.
    assert local_user(session).id == user.id

    principal = Principal(
        user_id=user.id,
        email=LOCAL_EMAIL,
        role="admin",
        org_id=None,
        display_name=user.display_name,
        issuer="disabled",
    )
    post = service.create_post(
        session, principal=principal, title="written with auth off", body="a local thought"
    )
    assert post["author"]["display_name"] == "local (auth disabled)"


def test_the_local_identity_is_labelled_not_disguised(session):
    """A reviewer reading this later should be able to tell it was written on an
    unauthenticated deployment."""
    from qra.security.service import local_user

    assert "auth disabled" in local_user(session).display_name
