"""Study series and the trainer (Track F).

Two rules carry most of this. A card never stores scripture — a stored copy is
one that can drift, and here the drift ends up in someone's memory. And no card
teaches a meaning, because no lexicon is loaded and inventing a gloss would be
the scripture-fabrication failure moved one step further into the learner.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from qra.models import (
    SeriesItem,
    SeriesProgress,
    StudySeries,
    TrainerCard,
    TrainerReview,
    User,
)
from qra.study import series as series_mod
from qra.study import trainer as trainer_mod
from qra.study.series import SeriesError
from qra.study.trainer import TrainerError


@pytest.fixture
def learner(session):
    from qra.security.service import register_user

    email = "study-learner@example.org"
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = register_user(
            session, email=email, password="pw-for-tests-1234", display_name="learner"
        )
        session.commit()
    return user.id


@pytest.fixture(autouse=True)
def _leave_no_trace(session):
    models = (TrainerReview, TrainerCard, SeriesProgress, SeriesItem, StudySeries)
    high = {m: session.scalar(select(func.max(m.id))) or 0 for m in models}
    yield
    for model in models:
        session.query(model).filter(model.id > high[model]).delete(synchronize_session=False)
    session.commit()


# --- the trainer's two rules ------------------------------------------------


def test_a_card_stores_a_reference_and_renders_the_verse(session, learner):
    """The card row holds `2:255`; the text comes from the database at review
    time. A stored copy could drift, and the drift would be silent and in
    someone's memory."""
    result = trainer_mod.add_card(session, learner, kind="reference_recall", subject="2:255")
    card = session.get(TrainerCard, result["card_id"])
    assert card.subject == "2:255"
    # The row itself carries no Arabic.
    assert not any("؀" <= ch <= "ۿ" for ch in card.subject)

    rendered = trainer_mod.render_card(session, card)
    assert "ٱللَّهُ" in rendered["answer"]
    assert rendered["citation"]["ref"] == "2:255"


def test_no_meaning_card_can_be_generated_without_a_lexicon(session):
    """Inventing a gloss is the scripture-fabrication failure with the
    consequence moved into the learner's memory."""
    kinds = trainer_mod.available_kinds(session)
    assert "vocabulary" not in kinds["available"]
    unavailable = {k["kind"] for k in kinds["unavailable"]}
    if unavailable:
        assert "vocabulary" in unavailable
        reason = next(k for k in kinds["unavailable"] if k["kind"] == "vocabulary")
        assert "no lexicon edition is loaded" in reason["why"]
        assert reason["unlocked_by"]


def test_a_card_pointing_at_nothing_is_refused_at_creation(session, learner):
    """A card whose subject does not resolve fails silently at review time,
    weeks later. It is rendered once before it is committed."""
    with pytest.raises(TrainerError, match="not an ayah"):
        trainer_mod.add_card(session, learner, kind="reference_recall", subject="999:1")
    assert not session.scalar(
        select(TrainerCard).where(TrainerCard.subject == "999:1")
    )


def test_an_unknown_card_kind_is_refused(session, learner):
    with pytest.raises(TrainerError, match="kind must be one of"):
        trainer_mod.add_card(session, learner, kind="vocabulary", subject="صبر")


# --- SM-2 -------------------------------------------------------------------


def test_the_interval_grows_on_success(session, learner):
    card = trainer_mod.add_card(session, learner, kind="reference_recall", subject="112:1")
    intervals = [trainer_mod.grade(session, card["card_id"], 5)["interval_days"] for _ in range(3)]
    assert intervals[0] == 1
    assert intervals[1] == 6
    assert intervals[2] > intervals[1]


def test_a_lapse_resets_the_interval_and_lowers_the_ease(session, learner):
    card = trainer_mod.add_card(session, learner, kind="reference_recall", subject="113:1")
    for _ in range(3):
        trainer_mod.grade(session, card["card_id"], 5)
    before = session.get(TrainerCard, card["card_id"]).ease
    lapsed = trainer_mod.grade(session, card["card_id"], 1)
    assert lapsed["interval_days"] == 1
    assert lapsed["repetitions"] == 0
    assert lapsed["lapses"] == 1
    assert lapsed["ease"] < before


def test_the_ease_never_falls_below_its_floor(session, learner):
    """Without the floor a repeatedly failed card appears every session, which
    is the point at which people abandon the deck."""
    card = trainer_mod.add_card(session, learner, kind="reference_recall", subject="114:1")
    for _ in range(20):
        result = trainer_mod.grade(session, card["card_id"], 0)
    assert result["ease"] >= trainer_mod.MIN_EASE


def test_a_grade_outside_the_scale_is_refused(session, learner):
    card = trainer_mod.add_card(session, learner, kind="reference_recall", subject="108:1")
    for bad in (-1, 6):
        with pytest.raises(TrainerError, match="between 0 and 5"):
            trainer_mod.grade(session, card["card_id"], bad)


def test_the_scheduler_reports_whether_it_has_been_right(session, learner):
    """A scheduler that never reports its recall rate is asserting its
    intervals rather than testing them."""
    card = trainer_mod.add_card(session, learner, kind="reference_recall", subject="110:1")
    trainer_mod.grade(session, card["card_id"], 5)
    trainer_mod.grade(session, card["card_id"], 5)
    trainer_mod.grade(session, card["card_id"], 1)

    stats = trainer_mod.review_stats(session, learner)
    assert stats["reviews"] == 3
    # A first sighting tests the material, not the interval, so it is excluded.
    assert stats["scheduled_reviews"] == 2
    assert stats["target"] == 0.9
    assert "about the schedule, not about the learner" in stats["reading"]


def test_stats_with_no_reviews_makes_no_claim(session, learner):
    stats = trainer_mod.review_stats(session, learner)
    assert stats["reviews"] == 0
    assert "no predictions to check" in stats["note"]


# --- series -----------------------------------------------------------------


def test_a_series_item_pointing_at_nothing_is_refused(session):
    """Checked at authoring time: a broken step found by a learner mid-sequence
    is a broken sequence."""
    for kind, target, match in (
        ("ayah_range", "999:1", "not an ayah"),
        ("root", "zzzz", "not a root"),
        ("concept", "not-a-concept", "not a concept"),
        ("grammar_query", "V:NONSENSE", "not a valid grammar query"),
    ):
        with pytest.raises(SeriesError, match=match):
            series_mod.create_series(
                session, title=f"broken {kind}", items=[{"kind": kind, "target": target}]
            )


def test_a_series_with_no_items_is_refused(session):
    with pytest.raises(SeriesError, match="teaches nothing"):
        series_mod.create_series(session, title="An empty series", items=[])


def test_a_series_stores_references_not_text(session):
    """A series that stored the verse could disagree with the corpus, and a
    learner has no way to notice."""
    created = series_mod.create_series(
        session,
        title="A reference series",
        items=[{"kind": "ayah_range", "target": "2:255", "note": "the throne verse"}],
    )
    item = session.scalar(
        select(SeriesItem).where(SeriesItem.series_id == created["id"])
    )
    assert item.target == "2:255"
    assert not any("؀" <= ch <= "ۿ" for ch in item.target)


def test_a_series_says_its_order_is_editorial(session):
    created = series_mod.create_series(
        session, title="An ordered series", items=[{"kind": "ayah_range", "target": "1:1"}]
    )
    assert created["provenance"] == "curated"
    assert "teaching judgement" in created["editorial"]


def test_progress_is_tracked_per_learner(session, learner):
    created = series_mod.create_series(
        session,
        title="A series with steps",
        items=[{"kind": "ayah_range", "target": "1:1"}, {"kind": "ayah_range", "target": "1:2"}],
    )
    assert created["completed"] == 0
    after = series_mod.mark_done(session, created["id"], learner, 1)
    assert after["completed"] == 1
    assert after["items"][0]["done"] is True
    assert after["items"][1]["done"] is False
    # Idempotent.
    assert series_mod.mark_done(session, created["id"], learner, 1)["completed"] == 1


def test_marking_a_step_that_does_not_exist_is_refused(session, learner):
    created = series_mod.create_series(
        session, title="A one-step series", items=[{"kind": "ayah_range", "target": "1:1"}]
    )
    with pytest.raises(SeriesError, match="has no step"):
        series_mod.mark_done(session, created["id"], learner, 99)


def test_cards_can_be_seeded_from_a_series(session, learner):
    created = series_mod.create_series(
        session,
        title="A seedable series",
        items=[
            {"kind": "ayah_range", "target": "112:1"},
            {"kind": "root", "target": "صبر"},
            {"kind": "concept", "target": "sabr"},
        ],
    )
    result = trainer_mod.seed_from_series(session, learner, created["id"])
    assert result["added"] == 2
    # A concept is something to read, not something to recall.
    assert any("concept" in s for s in result["skipped"])


def test_the_module_name_is_not_shadowed_by_a_function():
    """Exporting `series` alongside the module that defines it made
    `from qra.study import series` hand back the function."""
    from qra.study import series as module

    assert module.__name__ == "qra.study.series"
    import qra.study

    assert not hasattr(qra.study, "series") or callable(qra.study.get_series)


def test_a_refused_card_does_not_linger_in_the_transaction(session, learner):
    """It was added and flushed before being validated, so a caught error left
    the bad row pending for whatever committed next — the same mutate-then-
    validate shape as the claim registry and the rijal rebuild guard."""
    with pytest.raises(TrainerError):
        trainer_mod.add_card(session, learner, kind="reference_recall", subject="999:1")
    session.commit()
    assert not session.scalar(select(TrainerCard).where(TrainerCard.subject == "999:1"))
