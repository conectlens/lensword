"""Reminder-window recommendations (issue #89).

The issue's verification, restated: synthetic histories produce repeatable
recommendations, sparse data produces none, the engine never suggests outside
hard constraints, and a user can inspect why a time was suggested.

Most of these tests are about the service declining to answer. That is the
interesting behaviour — a recommender that always has an opinion is the thing
this design exists to avoid.
"""
from __future__ import annotations

from datetime import time

from app.domain.services.reminder_windows import (
    MIN_DELIVERIES_PER_SLOT,
    MIN_IMPROVEMENT,
    MIN_TOTAL_DELIVERIES,
    EngagementEvent,
    ReminderWindowRecommender,
)
from app.domain.value_objects import NotificationAction

ALL_HOURS = set(range(24))


def _events(hour: int, engaged: int, ignored: int) -> list[EngagementEvent]:
    return [
        EngagementEvent(local_hour=hour, action=NotificationAction.START_SESSION.value)
        for _ in range(engaged)
    ] + [EngagementEvent(local_hour=hour, action=None) for _ in range(ignored)]


def _recommend(events, current=time(9, 0), allowed=ALL_HOURS):
    return ReminderWindowRecommender.recommend(events, current, allowed)


# --- Refusing to recommend -------------------------------------------------


def test_no_recommendation_without_enough_history():
    """Sparse data produces no recommendation — the issue says so explicitly."""
    events = _events(hour=20, engaged=MIN_TOTAL_DELIVERIES - 1, ignored=0)

    assert _recommend(events) is None


def test_no_recommendation_from_a_slot_with_too_few_deliveries():
    """A slot can look perfect on two data points. That is not evidence the
    slot is better; it is evidence someone was awake twice."""
    events = _events(hour=9, engaged=0, ignored=12) + _events(
        hour=20, engaged=MIN_DELIVERIES_PER_SLOT - 1, ignored=0
    )

    assert _recommend(events) is None


def test_no_recommendation_for_a_marginal_improvement():
    """Without a margin, a near-tie would generate a prompt every week, and
    reminders that keep moving are worse than reminders at a mediocre hour."""
    events = _events(hour=9, engaged=5, ignored=5) + _events(hour=20, engaged=6, ignored=4)

    assert 0 < (0.6 - 0.5) < MIN_IMPROVEMENT
    assert _recommend(events) is None


def test_no_recommendation_when_the_current_time_is_already_best():
    events = _events(hour=9, engaged=9, ignored=1) + _events(hour=20, engaged=1, ignored=9)

    assert _recommend(events) is None


def test_no_recommendation_when_every_hour_is_disallowed():
    events = _events(hour=9, engaged=0, ignored=10) + _events(hour=20, engaged=10, ignored=0)

    assert _recommend(events, allowed=set()) is None


# --- Hard constraints ------------------------------------------------------


def test_a_disallowed_hour_is_never_suggested_however_good_it_looks():
    """The engine must never send outside hard constraints. 03:00 has a perfect
    record here and is still not offered, because the caller excluded it."""
    events = _events(hour=9, engaged=0, ignored=10) + _events(hour=3, engaged=10, ignored=0)

    assert _recommend(events, allowed=ALL_HOURS - {3}) is None


def test_the_best_allowed_hour_is_chosen_over_a_better_forbidden_one():
    events = (
        _events(hour=9, engaged=0, ignored=10)
        + _events(hour=3, engaged=10, ignored=0)
        + _events(hour=18, engaged=8, ignored=2)
    )

    recommendation = _recommend(events, allowed=ALL_HOURS - {3})

    assert recommendation is not None
    assert recommendation.hour == 18


# --- Recommending ----------------------------------------------------------


def test_a_clearly_better_hour_is_recommended():
    events = _events(hour=9, engaged=1, ignored=9) + _events(hour=20, engaged=9, ignored=1)

    recommendation = _recommend(events)

    assert recommendation is not None
    assert recommendation.hour == 20
    assert recommendation.suggested_rate == 0.9
    assert recommendation.current_rate == 0.1


def test_the_same_history_always_gives_the_same_answer():
    """Repeatability is a stated requirement. Dictionary iteration order and
    tie-breaking are the two places it could quietly be lost."""
    events = (
        _events(hour=9, engaged=1, ignored=9)
        + _events(hour=20, engaged=8, ignored=2)
        + _events(hour=7, engaged=8, ignored=2)
    )

    answers = {_recommend(list(reversed(events))).hour, _recommend(events).hour}

    assert len(answers) == 1


def test_a_tie_resolves_to_the_earliest_hour():
    events = (
        _events(hour=9, engaged=0, ignored=10)
        + _events(hour=20, engaged=8, ignored=2)
        + _events(hour=7, engaged=8, ignored=2)
    )

    assert _recommend(events).hour == 7


# --- What counts as engagement ---------------------------------------------


def test_snoozing_does_not_count_as_engagement():
    """Remind-me-later is an explicit deferral. Counting it would let a slot
    look good precisely because it kept being postponed."""
    events = _events(hour=9, engaged=0, ignored=10) + [
        EngagementEvent(local_hour=20, action=NotificationAction.REMIND_LATER.value)
        for _ in range(10)
    ]

    assert _recommend(events) is None


def test_skipping_does_not_count_as_engagement():
    events = _events(hour=9, engaged=0, ignored=10) + [
        EngagementEvent(local_hour=20, action=NotificationAction.SKIP_TODAY.value)
        for _ in range(10)
    ]

    assert _recommend(events) is None


# --- Explainability --------------------------------------------------------


def test_the_explanation_states_both_rates_and_both_sample_sizes():
    """A user is being asked to change when they are interrupted. The reason
    has to be checkable against the data rather than merely plausible."""
    events = _events(hour=9, engaged=1, ignored=9) + _events(hour=20, engaged=9, ignored=1)

    explanation = _recommend(events).explain()

    assert "90%" in explanation
    assert "10%" in explanation
    assert "20:00" in explanation
    # Sample sizes, so a reader can judge the evidence rather than trust the
    # percentages.
    assert explanation.count("10 reminders") == 2


def test_improvement_is_the_difference_between_the_two_rates():
    events = _events(hour=9, engaged=2, ignored=8) + _events(hour=20, engaged=8, ignored=2)

    recommendation = _recommend(events)

    assert round(recommendation.improvement, 10) == 0.6
