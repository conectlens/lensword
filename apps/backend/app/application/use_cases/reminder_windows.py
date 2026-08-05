"""Suggesting a better reminder time, and applying it only on request (#89).

Two use cases and a deliberate gap between them. Getting a recommendation
changes nothing; applying one is a separate, explicit call. The issue asks for
recommendations "for explicit acceptance" with "fixed schedules as the
default", and keeping them in separate operations is what makes that true of
the code rather than only of the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Callable

from app.domain.entities import RecallSettings, Reminder
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import (
    DesktopNotificationRepository,
    RecallSettingsRepository,
    ReminderRepository,
    UserRepository,
)
from app.domain.services.recall_delivery import is_within_quiet_hours, quiet_hours_bounds
from app.domain.services.reminder_windows import (
    EngagementEvent,
    ReminderWindowRecommender,
    WindowRecommendation,
)
from app.domain.value_objects import utcnow, zone_for

# How far back engagement is read. Long enough to accumulate a sample, short
# enough that a habit abandoned months ago stops voting.
HISTORY_WINDOW = timedelta(days=90)


@dataclass(frozen=True)
class ReminderWindowSuggestion:
    reminder_id: int
    current_hour: int
    recommendation: WindowRecommendation

    @property
    def explanation(self) -> str:
        return self.recommendation.explain()


def _allowed_hours(settings: RecallSettings) -> set[int]:
    """Hours a reminder may be moved to.

    An hour is excluded if any part of it falls inside quiet hours. Checking
    only the top of the hour would let a 21:30 quiet-hours start be worked
    around by recommending 21:00, which is not what the user asked for.
    """
    start, end = quiet_hours_bounds(settings)
    if start is None or end is None:
        return set(range(24))
    return {
        hour
        for hour in range(24)
        if not is_within_quiet_hours(start, end, time(hour, 0))
        and not is_within_quiet_hours(start, end, time(hour, 59))
    }


class SuggestReminderWindowUseCase:
    """Read-only. Produces a suggestion or nothing; changes no schedule."""

    def __init__(
        self,
        reminders: ReminderRepository,
        notifications: DesktopNotificationRepository,
        settings_repo: RecallSettingsRepository,
        users: UserRepository,
        clock: Callable[[], datetime] = utcnow,
        history_window: timedelta = HISTORY_WINDOW,
    ):
        self.reminders = reminders
        self.notifications = notifications
        self.settings_repo = settings_repo
        self.users = users
        self.clock = clock
        self.history_window = history_window

    def execute(self, user_id: int, reminder_id: int) -> ReminderWindowSuggestion | None:
        reminder = self._owned(user_id, reminder_id)
        settings = self.settings_repo.get_by_user(user_id) or RecallSettings(user_id=user_id)
        user = self.users.get_by_id(user_id)
        zone = zone_for(user.time_zone if user else "UTC")

        history = self.notifications.list_engagement_history(
            user_id, self.clock() - self.history_window
        )
        # Bucketed on the user's clock, not UTC: otherwise the recommendation
        # would move whenever they travelled, and would be wrong by the offset
        # for everyone outside UTC.
        events = [
            EngagementEvent(local_hour=_to_local(n.created_at, zone).hour, action=n.action)
            for n in history
        ]

        recommendation = ReminderWindowRecommender.recommend(
            events, reminder.time_of_day, _allowed_hours(settings)
        )
        if recommendation is None:
            return None
        return ReminderWindowSuggestion(
            reminder_id=reminder_id,
            current_hour=reminder.time_of_day.hour,
            recommendation=recommendation,
        )

    def _owned(self, user_id: int, reminder_id: int) -> Reminder:
        reminder = self.reminders.get_by_id(reminder_id)
        if reminder is None:
            raise EntityNotFoundError("Reminder", reminder_id)
        if reminder.user_id != user_id:
            raise PermissionDeniedError("This reminder belongs to another account")
        return reminder


class AcceptReminderWindowUseCase:
    """Move a reminder to a suggested hour, at the user's request.

    Re-derives the suggestion rather than trusting an hour from the client.
    Otherwise this would be an endpoint for setting a reminder to any hour at
    all under the cover of "accepting a recommendation" — including one inside
    the account's own quiet hours.
    """

    def __init__(
        self,
        reminders: ReminderRepository,
        suggest: SuggestReminderWindowUseCase,
        jobs=None,
    ):
        self.reminders = reminders
        self.suggest = suggest
        # Re-registers the moved reminder. Absent outside a running
        # application, where there are no jobs to move.
        self.jobs = jobs

    def execute(self, user_id: int, reminder_id: int, accepted_hour: int) -> Reminder:
        suggestion = self.suggest.execute(user_id, reminder_id)
        if suggestion is None or suggestion.recommendation.hour != accepted_hour:
            # Stale: the recommendation changed or lapsed between being shown
            # and being accepted. Refused rather than applied, because the
            # explanation the user agreed to no longer describes what would
            # happen.
            raise EntityNotFoundError("ReminderWindowRecommendation", reminder_id)

        reminder = self.reminders.get_by_id(reminder_id)
        current = reminder.time_of_day
        reminder.trigger_time = f"{accepted_hour:02d}:{current.minute:02d}"
        saved = self.reminders.update(reminder)
        if self.jobs is not None:
            self.jobs.schedule(saved)
        return saved


def _to_local(moment: datetime, zone) -> datetime:
    """Naive-UTC to naive-local. Every datetime in this domain is naive-but-UTC
    by convention (see value_objects.utcnow), so the tzinfo is attached rather
    than assumed present."""
    return moment.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
