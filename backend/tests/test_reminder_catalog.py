"""The reminder job catalog (issue #98).

The issue's verification asks for clock-controlled coverage of every job,
opt-out, quiet hours and duplicate events, and — the part that matters most —
that prepared sessions reconcile exactly with the displayed word counts.

So the emphasis here is on jobs *not* firing, and on the numbers being the
ones that were read rather than ones that sound right. A reminder claiming
seven words are due when three are is worse than no reminder: it teaches the
user that the number is decoration.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.domain.services.reminder_catalog import (
    COOLDOWN,
    DAILY_NOTIFICATION_CAP,
    INACTIVITY_DAYS,
    JobKind,
    LearnerFacts,
    ReminderCatalog,
    SuppressionReason,
)

NOW = datetime(2026, 8, 2, 9, 0)


def _facts(**overrides) -> LearnerFacts:
    fields = dict(today=date(2026, 8, 2))
    fields.update(overrides)
    return LearnerFacts(**fields)


def _decide(kind, facts=None, **kwargs):
    return ReminderCatalog.decide(kind, facts or _facts(), now=NOW, **kwargs)


# --- Every job has something real to say, or stays quiet -------------------


def test_due_words_fires_only_when_words_are_actually_due():
    assert _decide(JobKind.DUE_WORDS, _facts(due_count=3)).should_notify is True
    assert _decide(JobKind.DUE_WORDS, _facts(due_count=0)).should_notify is False


def test_due_words_quotes_the_count_it_was_given():
    """Not rounded, not estimated. The number is the one that was read."""
    decision = _decide(JobKind.DUE_WORDS, _facts(due_count=3))

    assert decision.facts == {"due_count": 3}


def test_daily_study_stays_quiet_on_an_empty_queue():
    """A daily nudge that fires with nothing to study is the fastest way to
    teach someone to ignore it."""
    assert _decide(JobKind.DAILY_STUDY, _facts(due_count=0, new_words_available=0)).reason is (
        SuppressionReason.NOTHING_TO_SAY
    )


def test_daily_study_stays_quiet_once_the_user_has_already_studied():
    facts = _facts(due_count=5, sessions_today=1)

    assert _decide(JobKind.DAILY_STUDY, facts).should_notify is False


def test_missed_session_fires_only_the_day_after():
    """Two days on it is the inactivity nudge's job, and both firing would be
    two notifications about the same silence."""
    assert _decide(JobKind.MISSED_SESSION, _facts(days_since_last_session=1)).should_notify is True
    assert _decide(JobKind.MISSED_SESSION, _facts(days_since_last_session=2)).should_notify is False
    assert _decide(JobKind.MISSED_SESSION, _facts(days_since_last_session=0)).should_notify is False


def test_inactive_user_waits_out_a_weekend():
    """Short enough to catch someone drifting away, long enough not to chase
    two days off."""
    assert _decide(
        JobKind.INACTIVE_USER, _facts(days_since_last_session=INACTIVITY_DAYS - 1)
    ).should_notify is False
    assert _decide(
        JobKind.INACTIVE_USER, _facts(days_since_last_session=INACTIVITY_DAYS)
    ).should_notify is True


def test_inactive_user_says_nothing_to_someone_who_never_started():
    assert _decide(JobKind.INACTIVE_USER, _facts(days_since_last_session=None)).should_notify is False


def test_goal_progress_stops_once_the_goal_is_met():
    """After it is met the notification is noise."""
    met = _facts(goal_minutes=10, minutes_studied_today=10)
    short = _facts(goal_minutes=10, minutes_studied_today=4)

    assert _decide(JobKind.GOAL_PROGRESS, met).should_notify is False
    assert _decide(JobKind.GOAL_PROGRESS, short).should_notify is True


def test_goal_progress_reports_the_remainder_arithmetically():
    decision = _decide(JobKind.GOAL_PROGRESS, _facts(goal_minutes=10, minutes_studied_today=4))

    assert decision.facts["minutes_remaining"] == 6


def test_goal_progress_says_nothing_when_no_goal_is_set():
    """There is nothing to be short of."""
    assert _decide(JobKind.GOAL_PROGRESS, _facts(goal_minutes=0)).should_notify is False


def test_weekly_summary_is_sent_even_on_a_quiet_week():
    """That is what a summary is for."""
    facts = _facts(due_count=0, days_since_last_session=6)

    assert _decide(JobKind.WEEKLY_SUMMARY, facts).should_notify is True


def test_weekly_summary_is_not_sent_to_someone_who_never_had_a_session():
    """A report about nothing."""
    assert _decide(JobKind.WEEKLY_SUMMARY, _facts(days_since_last_session=None)).should_notify is False


# --- The reconciliation the issue calls out --------------------------------


def test_a_prepared_session_quotes_its_own_size_not_the_backlog():
    """The issue is explicit that prepared sessions must reconcile exactly with
    the displayed word count. Those differ whenever a session limit is smaller
    than the backlog, and quoting the backlog would promise 40 words and then
    show 20."""
    facts = _facts(due_count=40, prepared_session_size=20)

    decision = _decide(JobKind.PREPARED_SESSION, facts)

    assert decision.facts == {"prepared_session_size": 20}


def test_a_prepared_session_of_nothing_is_not_announced():
    assert _decide(JobKind.PREPARED_SESSION, _facts(prepared_session_size=0)).should_notify is False


# --- Suppression, and why it was suppressed --------------------------------


def test_opting_out_beats_every_other_reason():
    """Both may be true, but only opting out explains why this job will never
    be seen again."""
    facts = _facts(due_count=0, notifications_sent_today=DAILY_NOTIFICATION_CAP)

    assert _decide(JobKind.DUE_WORDS, facts, opted_out=True).reason is SuppressionReason.OPTED_OUT


def test_pausing_suppresses_without_being_an_opt_out():
    assert _decide(JobKind.DUE_WORDS, _facts(due_count=5), paused=True).reason is (
        SuppressionReason.PAUSED
    )


def test_quiet_hours_are_recorded_as_the_reason():
    decision = _decide(JobKind.DUE_WORDS, _facts(due_count=5), in_quiet_hours=True)

    assert decision.reason is SuppressionReason.QUIET_HOURS


def test_the_daily_cap_is_global_across_job_kinds():
    """Seven kinds each politely limiting themselves to one a day is still
    seven interruptions."""
    facts = _facts(due_count=5, notifications_sent_today=DAILY_NOTIFICATION_CAP)

    for kind in JobKind:
        assert _decide(kind, facts).reason is SuppressionReason.FREQUENCY_CAP, kind


def test_the_cooldown_spreads_notifications_out():
    """Without it, four jobs coming due in the same minute spend the whole
    daily budget at once and the cap spreads nothing."""
    just_notified = _facts(due_count=5, last_notified_at=NOW - COOLDOWN + timedelta(minutes=1))

    assert _decide(JobKind.DUE_WORDS, just_notified).reason is SuppressionReason.COOLDOWN


def test_the_cooldown_expires():
    expired = _facts(due_count=5, last_notified_at=NOW - COOLDOWN - timedelta(minutes=1))

    assert _decide(JobKind.DUE_WORDS, expired).should_notify is True


def test_a_first_ever_notification_is_not_held_by_the_cooldown():
    assert _decide(JobKind.DUE_WORDS, _facts(due_count=5, last_notified_at=None)).should_notify is True


def test_a_suppressed_decision_carries_no_facts_to_render():
    """So a caller cannot accidentally render a notification it was told not to
    send."""
    decision = _decide(JobKind.DUE_WORDS, _facts(due_count=5), paused=True)

    assert decision.facts is None


@pytest.mark.parametrize("kind", list(JobKind))
def test_every_job_kind_is_decidable(kind):
    """A kind added to the enum without an eligibility rule would silently
    never fire."""
    decision = _decide(kind, _facts())

    assert isinstance(decision.reason, SuppressionReason)


@pytest.mark.parametrize("kind", list(JobKind))
def test_no_job_ever_fires_during_quiet_hours(kind):
    """The hard constraint. Generous facts, so only quiet hours can be the
    reason nothing is sent."""
    generous = _facts(
        due_count=9, new_words_available=9, days_since_last_session=INACTIVITY_DAYS,
        goal_minutes=30, minutes_studied_today=0, prepared_session_size=5,
    )

    assert _decide(kind, generous, in_quiet_hours=True).should_notify is False, kind


# --- Backfill after downtime -----------------------------------------------


def test_a_job_firing_long_after_its_slot_is_discarded():
    """After downtime the scheduler catches up on everything it missed at
    once. A reminder about yesterday morning arriving this afternoon is not
    the thing the user was promised."""
    decision = _decide(
        JobKind.DUE_WORDS,
        _facts(due_count=5),
        scheduled_for=NOW - timedelta(days=1),
    )

    assert decision.reason is SuppressionReason.STALE


def test_a_job_a_little_late_still_fires():
    """A scheduler busy for twenty minutes should still deliver."""
    decision = _decide(
        JobKind.DUE_WORDS,
        _facts(due_count=5),
        scheduled_for=NOW - timedelta(minutes=20),
    )

    assert decision.should_notify is True


def test_staleness_is_checked_before_the_daily_cap():
    """Otherwise a backlog of stale occurrences would spend the day's budget on
    notifications about yesterday and suppress today's real one."""
    decision = _decide(
        JobKind.DUE_WORDS,
        _facts(due_count=5, notifications_sent_today=DAILY_NOTIFICATION_CAP),
        scheduled_for=NOW - timedelta(days=1),
    )

    assert decision.reason is SuppressionReason.STALE


def test_a_job_with_no_scheduled_time_is_never_stale():
    """Not every caller knows its slot; absence must not mean discarded."""
    assert _decide(JobKind.DUE_WORDS, _facts(due_count=5), scheduled_for=None).should_notify is True
