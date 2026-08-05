"""Which scheduled nudges exist, and whether each one has earned the right to
interrupt someone (issue #98).

The catalog is a closed set of job kinds, each with an eligibility rule
expressed against *facts read from the database*. That last part is the
constraint the issue is emphatic about: an AI may phrase a notification, but
the counts in it are computed here and are never invented. A reminder that
says "7 words are due" when three are is worse than no reminder — it teaches
the user that the number is decoration.

Everything is pure and takes its facts as an argument, so a job's eligibility
can be tested at any instant without a clock, a database, or a scheduler.

Suppression is a *reason*, not a boolean. "Nothing to review" and "you already
had two today" both mean no notification, but only one of them is worth
telling the user about, and only one is a bug if it happens every day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum


class JobKind(str, Enum):
    """The closed set of scheduled nudges.

    Closed deliberately: every member has to have an eligibility rule and a
    frequency cap, so adding one is a decision about interrupting people
    rather than a new string.
    """

    DAILY_STUDY = "daily_study"
    DUE_WORDS = "due_words"
    MISSED_SESSION = "missed_session"
    WEEKLY_SUMMARY = "weekly_summary"
    GOAL_PROGRESS = "goal_progress"
    INACTIVE_USER = "inactive_user"
    PREPARED_SESSION = "prepared_session"


class SuppressionReason(str, Enum):
    """Why a job that was scheduled did not notify.

    Recorded rather than discarded. "Nothing was due" is healthy; "the daily
    cap was already spent" every single day means the caps are wrong, and the
    two are indistinguishable from the absence of a notification.
    """

    NOT_SUPPRESSED = "not_suppressed"
    NOTHING_TO_SAY = "nothing_to_say"
    QUIET_HOURS = "quiet_hours"
    FREQUENCY_CAP = "frequency_cap"
    COOLDOWN = "cooldown"
    ALREADY_SENT = "already_sent"
    # Fired so long after its scheduled time that it is no longer about now.
    STALE = "stale"
    OPTED_OUT = "opted_out"
    PAUSED = "paused"


@dataclass(frozen=True)
class LearnerFacts:
    """Everything the catalog is allowed to reason about.

    Passed in rather than queried, so eligibility stays pure — and so the
    numbers a notification quotes are demonstrably the ones that were read,
    not ones a model produced.
    """

    due_count: int = 0
    new_words_available: int = 0
    days_since_last_session: int | None = None
    sessions_today: int = 0
    goal_minutes: int = 0
    minutes_studied_today: int = 0
    prepared_session_size: int = 0
    notifications_sent_today: int = 0
    last_notified_at: datetime | None = None
    today: date = date(2026, 1, 1)


@dataclass(frozen=True)
class JobDecision:
    kind: JobKind
    reason: SuppressionReason
    # The facts the message may quote. Empty when suppressed, so a caller
    # cannot accidentally render a notification it was told not to send.
    facts: dict[str, int] | None = None

    @property
    def should_notify(self) -> bool:
        return self.reason is SuppressionReason.NOT_SUPPRESSED


# How many notifications a day, in total, across every job kind. The cap is
# global rather than per-kind on purpose: seven kinds each politely limiting
# themselves to one a day is still seven interruptions.
DAILY_NOTIFICATION_CAP = 4

# Minimum gap between any two notifications. Without it, four jobs coming due
# in the same minute spend the whole daily budget at once and the cap does not
# actually spread anything out.
COOLDOWN = timedelta(hours=2)

# Days of silence before an inactive-user nudge. Short enough to catch someone
# drifting away, long enough not to chase a weekend off.
INACTIVITY_DAYS = 4

# How late a job may fire and still be worth firing. After downtime the
# scheduler catches up on everything it missed at once, and without this every
# missed occurrence arrives together — the storm the issue asks to avoid. The
# daily cap alone would not help: it would let four *stale* notifications
# through and then suppress today's real one.
MAX_LATENESS = timedelta(hours=3)


class ReminderCatalog:
    """Stateless. Decides whether one job kind may notify, given the facts."""

    @staticmethod
    def decide(
        kind: JobKind,
        facts: LearnerFacts,
        *,
        opted_out: bool = False,
        paused: bool = False,
        in_quiet_hours: bool = False,
        now: datetime | None = None,
        scheduled_for: datetime | None = None,
        max_lateness: timedelta = MAX_LATENESS,
    ) -> JobDecision:
        # Ordered most-decisive first, so the recorded reason is the one a
        # person would give. "You opted out" beats "nothing was due" even when
        # both are true, because only the first explains why they will never
        # see this job again.
        if opted_out:
            return JobDecision(kind, SuppressionReason.OPTED_OUT)
        if paused:
            return JobDecision(kind, SuppressionReason.PAUSED)
        if in_quiet_hours:
            return JobDecision(kind, SuppressionReason.QUIET_HOURS)
        # Checked before the caps, so a backlog of stale occurrences is
        # discarded rather than spending the day's budget on notifications
        # about yesterday.
        if _is_stale(now, scheduled_for, max_lateness):
            return JobDecision(kind, SuppressionReason.STALE)
        if facts.notifications_sent_today >= DAILY_NOTIFICATION_CAP:
            return JobDecision(kind, SuppressionReason.FREQUENCY_CAP)
        if _within_cooldown(facts, now):
            return JobDecision(kind, SuppressionReason.COOLDOWN)

        content = _content_for(kind, facts)
        if content is None:
            return JobDecision(kind, SuppressionReason.NOTHING_TO_SAY)
        return JobDecision(kind, SuppressionReason.NOT_SUPPRESSED, facts=content)


def _is_stale(
    now: datetime | None, scheduled_for: datetime | None, max_lateness: timedelta
) -> bool:
    if now is None or scheduled_for is None:
        return False
    return now - scheduled_for > max_lateness


def _within_cooldown(facts: LearnerFacts, now: datetime | None) -> bool:
    if facts.last_notified_at is None or now is None:
        return False
    return now - facts.last_notified_at < COOLDOWN


def _content_for(kind: JobKind, facts: LearnerFacts) -> dict[str, int] | None:
    """The counts this job would quote, or None if it has nothing to say.

    Every value is read off the facts. Nothing is estimated, rounded up, or
    filled in when missing — a job with no real number to report is suppressed
    rather than sent with a plausible one.
    """
    if kind is JobKind.DUE_WORDS:
        return {"due_count": facts.due_count} if facts.due_count > 0 else None

    if kind is JobKind.DAILY_STUDY:
        # Nothing to study means nothing to say. A daily nudge that fires on an
        # empty queue is the fastest way to teach someone to ignore it.
        available = facts.due_count + facts.new_words_available
        if available <= 0 or facts.sessions_today > 0:
            return None
        return {"due_count": facts.due_count, "new_words": facts.new_words_available}

    if kind is JobKind.MISSED_SESSION:
        if facts.sessions_today > 0 or facts.days_since_last_session != 1:
            return None
        return {"days_since_last_session": 1, "due_count": facts.due_count}

    if kind is JobKind.INACTIVE_USER:
        days = facts.days_since_last_session
        if days is None or days < INACTIVITY_DAYS:
            return None
        return {"days_since_last_session": days}

    if kind is JobKind.GOAL_PROGRESS:
        # Only worth saying while the goal is still reachable today. After it
        # is met the notification is noise; with no goal set there is nothing
        # to be short of.
        if facts.goal_minutes <= 0 or facts.minutes_studied_today >= facts.goal_minutes:
            return None
        return {
            "goal_minutes": facts.goal_minutes,
            "minutes_studied": facts.minutes_studied_today,
            "minutes_remaining": facts.goal_minutes - facts.minutes_studied_today,
        }

    if kind is JobKind.WEEKLY_SUMMARY:
        # Sent even on a quiet week — that is the point of a summary — but not
        # to someone who has never had a session, for whom it is a report
        # about nothing.
        if facts.days_since_last_session is None:
            return None
        return {"due_count": facts.due_count}

    if kind is JobKind.PREPARED_SESSION:
        # The count must match what the session will actually contain, which
        # is why it is the prepared size rather than the due count: they differ
        # whenever a session limit is smaller than the backlog.
        return (
            {"prepared_session_size": facts.prepared_session_size}
            if facts.prepared_session_size > 0
            else None
        )

    return None
