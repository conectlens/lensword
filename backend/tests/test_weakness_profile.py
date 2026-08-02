"""Mistake memory and weakness detection (issue #134, split from #77).

The thing worth guarding against is confident nonsense: three wrong answers on
a Tuesday becoming "you struggle with irregular verbs", which the learner then
believes and studies. So most of these tests are about the profile declining
to claim things.
"""
from __future__ import annotations

import pytest

from app.domain.services.weakness import (
    MIN_CONFUSIONS_FOR_PAIR,
    MIN_OCCURRENCES_FOR_CATEGORY,
    ErrorCategory,
    MistakeEvent,
    WeaknessProfileService,
    categorise,
)


def _events(category: ErrorCategory, count: int, word_id: int = 1) -> list[MistakeEvent]:
    return [MistakeEvent(user_id=1, word_id=word_id, category=category) for _ in range(count)]


def _confusion(word_id: int, other: int, count: int) -> list[MistakeEvent]:
    return [
        MistakeEvent(
            user_id=1,
            word_id=word_id,
            category=ErrorCategory.WRONG_WORD,
            confused_with_word_id=other,
        )
        for _ in range(count)
    ]


# --- Declining to claim things ---------------------------------------------


def test_no_history_is_reported_as_not_knowing_yet():
    """Not as an empty profile, which reads as "you have no weaknesses"."""
    profile = WeaknessProfileService.build([])

    assert profile.insufficient_data is True
    assert profile.categories == []


def test_a_category_below_the_threshold_is_not_named():
    """A learner told they are weak at something after two slips will either
    dismiss the feature or, worse, believe it."""
    profile = WeaknessProfileService.build(
        _events(ErrorCategory.SPELLING, MIN_OCCURRENCES_FOR_CATEGORY - 1)
    )

    assert profile.categories == []
    assert profile.insufficient_data is True


def test_mistakes_that_are_too_scattered_to_name_still_count():
    """The total is real even when nothing crosses the threshold — the profile
    knows there were mistakes, just not what they mean."""
    events = _events(ErrorCategory.SPELLING, 1) + _events(ErrorCategory.SENSE, 1)

    profile = WeaknessProfileService.build(events)

    assert profile.total_mistakes == 2
    assert profile.insufficient_data is True


def test_a_single_confusion_is_a_slip_not_a_pattern():
    profile = WeaknessProfileService.build(_confusion(1, 2, MIN_CONFUSIONS_FOR_PAIR - 1))

    assert profile.confused_pairs == []


# --- Naming what is real ---------------------------------------------------


def test_a_repeated_category_is_reported_with_its_count():
    profile = WeaknessProfileService.build(_events(ErrorCategory.INFLECTION, 4))

    assert profile.categories[0].category is ErrorCategory.INFLECTION
    assert profile.categories[0].occurrences == 4


def test_the_share_is_carried_alongside_the_count_not_instead_of_it():
    """60% of five mistakes and 60% of five hundred are very different
    claims."""
    events = _events(ErrorCategory.SPELLING, 6) + _events(ErrorCategory.SENSE, 4)

    profile = WeaknessProfileService.build(events)

    top = profile.categories[0]
    assert top.occurrences == 6
    assert top.share == pytest.approx(0.6)


def test_categories_are_ordered_by_frequency():
    events = _events(ErrorCategory.SPELLING, 3) + _events(ErrorCategory.SENSE, 7)

    profile = WeaknessProfileService.build(events)

    assert [c.category for c in profile.categories] == [
        ErrorCategory.SENSE,
        ErrorCategory.SPELLING,
    ]


def test_equal_counts_have_a_stable_order():
    """Otherwise the profile reshuffles between requests for no reason the
    learner can see."""
    events = _events(ErrorCategory.SPELLING, 3) + _events(ErrorCategory.SENSE, 3)

    first = WeaknessProfileService.build(events)
    second = WeaknessProfileService.build(list(reversed(events)))

    assert [c.category for c in first.categories] == [c.category for c in second.categories]


def test_only_the_top_categories_are_reported():
    """A profile listing everything gives no sense of priority."""
    events: list[MistakeEvent] = []
    for category in ErrorCategory:
        events.extend(_events(category, 5))

    profile = WeaknessProfileService.build(events, top_categories=2)

    assert len(profile.categories) == 2


# --- Confused pairs --------------------------------------------------------


def test_a_repeated_confusion_becomes_a_pair():
    profile = WeaknessProfileService.build(_confusion(1, 2, MIN_CONFUSIONS_FOR_PAIR))

    assert profile.confused_pairs[0].occurrences == MIN_CONFUSIONS_FOR_PAIR


def test_a_pair_is_the_same_pair_in_either_direction():
    """A learner who confused them both ways would otherwise see two entries
    describing one problem."""
    events = _confusion(1, 2, 1) + _confusion(2, 1, 1)

    profile = WeaknessProfileService.build(events)

    assert len(profile.confused_pairs) == 1
    assert profile.confused_pairs[0].occurrences == 2


def test_a_word_confused_with_itself_is_dropped():
    """That is a recording bug, not a pattern."""
    profile = WeaknessProfileService.build(_confusion(1, 1, 5))

    assert profile.confused_pairs == []


def test_pairs_are_ordered_by_frequency():
    events = _confusion(1, 2, 2) + _confusion(3, 4, 5)

    profile = WeaknessProfileService.build(events)

    assert profile.confused_pairs[0].word_id == 3


# --- Classifying one wrong answer ------------------------------------------


def test_a_skipped_answer_is_not_recalled_rather_than_wrong():
    """Usually means never learned rather than mislearned, and the remedy
    differs."""
    category, confused = categorise("skipped", None, "gato")

    assert category is ErrorCategory.NOT_RECALLED
    assert confused is None


def test_an_empty_answer_is_treated_as_not_recalled():
    assert categorise("incorrect", "   ", "gato")[0] is ErrorCategory.NOT_RECALLED


def test_answering_with_another_word_the_learner_studies_names_the_confusion():
    category, confused = categorise("incorrect", "perro", "gato", {"perro": 7})

    assert category is ErrorCategory.WRONG_WORD
    assert confused == 7


def test_a_misspelling_that_resembles_a_word_is_not_called_a_confusion():
    """Only an attempt that *is* another word they are learning counts. A
    random typo resembling one is not evidence of confusing the two."""
    category, confused = categorise("incorrect", "gatoo", "gato", {"perro": 7})

    assert category is ErrorCategory.SPELLING
    assert confused is None


def test_a_near_miss_is_a_spelling_error():
    assert categorise("incorrect", "recieve", "receive")[0] is ErrorCategory.SPELLING


def test_something_unrecognisable_is_unknown_rather_than_guessed():
    """A classifier that guesses produces a profile that guesses, and the
    learner cannot tell the difference."""
    assert categorise("incorrect", "xyzzy", "gato")[0] is ErrorCategory.UNKNOWN


def test_an_answer_identical_to_the_target_is_not_filed_as_a_learner_error():
    """Marked wrong but textually identical — a grader disagreement or a
    trailing-space artefact."""
    assert categorise("incorrect", " gato ", "gato")[0] is ErrorCategory.UNKNOWN


def test_classification_ignores_case():
    category, confused = categorise("incorrect", "Perro", "gato", {"perro": 7})

    assert category is ErrorCategory.WRONG_WORD
    assert confused == 7
