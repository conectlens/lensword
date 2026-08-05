"""CEFR progress across levels (issue #143).

The arithmetic is trivial. What is worth pinning is what the view refuses to
do: fold unlevelled words into levels, drop empty levels, or let a word stop
counting as mastered merely because a review came due.
"""
from __future__ import annotations

from app.domain.services.cefr_progress import (
    CEFR_LEVELS,
    MASTERY_STRENGTH,
    ScoredWord,
    build_progress,
)


def _word(level: str | None = "A1", strength: float = 0.0, repetitions: int = 0) -> ScoredWord:
    return ScoredWord(cefr_level=level, strength=strength, repetitions=repetitions)


def _level(progress, name: str):
    return next(level for level in progress.levels if level.level == name)


# --- Every level is present ------------------------------------------------


def test_all_six_levels_appear_even_when_empty():
    """A gap in the axis reads as "no data was collected"; a zero reads as "you
    have nothing here yet", and the second is the true one."""
    progress = build_progress([_word(level="A1")])

    assert [level.level for level in progress.levels] == list(CEFR_LEVELS)


def test_levels_are_ordered_from_a1_to_c2():
    progress = build_progress([_word(level="C2"), _word(level="A1")])

    assert [level.level for level in progress.levels] == ["A1", "A2", "B1", "B2", "C1", "C2"]


def test_an_empty_deck_still_reports_every_level():
    progress = build_progress([])

    assert len(progress.levels) == 6
    assert progress.total_words == 0
    assert all(level.total == 0 for level in progress.levels)


# --- Unlevelled words ------------------------------------------------------


def test_words_with_no_level_are_counted_separately():
    """Most decks are full of them. Distributing them across levels would
    invent data."""
    progress = build_progress([_word(level=None), _word(level="A1")])

    assert progress.unlevelled is not None
    assert progress.unlevelled.total == 1
    assert _level(progress, "A1").total == 1


def test_unlevelled_words_are_not_dropped_from_the_total():
    """Otherwise the parts stop adding up to the learner's own word count,
    which is the fastest way to make a progress screen untrustworthy."""
    progress = build_progress([_word(level=None), _word(level=None), _word(level="B1")])

    assert progress.total_words == 3
    assert progress.levelled_words == 1
    assert progress.unlevelled.total == 2


def test_an_unrecognised_level_is_treated_as_unknown_rather_than_raising():
    """A value this build has no meaning for is data, not a crash."""
    progress = build_progress([_word(level="Z9")])

    assert progress.unlevelled.total == 1


def test_level_matching_ignores_case_and_space():
    progress = build_progress([_word(level=" b1 ")])

    assert _level(progress, "B1").total == 1
    assert progress.unlevelled is None


def test_a_deck_with_every_word_levelled_reports_no_unlevelled_bucket():
    progress = build_progress([_word(level="A1")])

    assert progress.unlevelled is None


# --- Mastery ---------------------------------------------------------------


def test_a_strong_reviewed_word_counts_as_mastered():
    progress = build_progress([_word(strength=MASTERY_STRENGTH, repetitions=4)])

    assert _level(progress, "A1").mastered == 1


def test_a_word_that_is_due_still_counts_as_mastered():
    """WordStatus reports NEEDS_REVIEW for anything past its due date, mastered
    or not. Progress that dropped every time a review came round would be
    measuring the schedule rather than the learner."""
    # Strength is what decides it here; being due is not represented at all.
    progress = build_progress([_word(strength=95, repetitions=10)])

    assert _level(progress, "A1").mastered == 1


def test_an_unreviewed_word_is_never_mastered():
    """Strength on a word with no reviews is not evidence of anything."""
    progress = build_progress([_word(strength=100, repetitions=0)])

    assert _level(progress, "A1").mastered == 0


def test_a_weak_word_is_started_but_not_mastered():
    progress = build_progress([_word(strength=MASTERY_STRENGTH - 1, repetitions=2)])

    level = _level(progress, "A1")
    assert (level.started, level.mastered) == (1, 0)


def test_a_new_word_is_neither_started_nor_mastered():
    progress = build_progress([_word()])

    level = _level(progress, "A1")
    assert (level.total, level.started, level.mastered) == (1, 0, 0)


# --- Shares ----------------------------------------------------------------


def test_mastery_share_is_of_what_the_learner_holds():
    """Not of the level itself — we do not know how many B2 words exist, and
    pretending to would turn a real fraction into an invented one."""
    progress = build_progress(
        [_word(level="B2", strength=90, repetitions=3), _word(level="B2")]
    )

    assert _level(progress, "B2").mastery_share == 0.5


def test_an_empty_level_reports_zero_rather_than_dividing_by_nothing():
    progress = build_progress([_word(level="A1")])

    assert _level(progress, "C2").mastery_share == 0.0


def test_a_fully_mastered_level_reports_one():
    progress = build_progress([_word(level="A2", strength=100, repetitions=5)])

    assert _level(progress, "A2").mastery_share == 1.0
