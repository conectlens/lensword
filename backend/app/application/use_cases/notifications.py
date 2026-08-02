"""Use cases for the desktop notification outbox (issue #27).

The desktop shell is a remote client (ADR 0002), so the two operations it
needs are "what do I owe the tray" and "I have shown these". Both are
deliberately application-layer rather than raw repository calls from the
router: the staleness window and the collection bound are policy, and issue
#88 will add action handling on top of the same acknowledgement path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from app.domain.entities import DesktopNotification
from app.domain.exceptions import EntityNotFoundError, NotificationExpiredError
from app.domain.repositories import DesktopNotificationRepository
from app.domain.value_objects import (
    NOTIFICATION_ACTION_TTL,
    REMIND_LATER_DELAY,
    NotificationAction,
    utcnow,
)

# A notification the shell never collected within this window is not shown at
# all. Reminders are about a moment — telling someone at 09:00 Tuesday to do
# yesterday's 20:00 review is noise, not a late delivery — and without a cutoff
# a laptop opened after a week away would fire its whole backlog at once.
DEFAULT_MAX_AGE = timedelta(hours=12)

# One collection returns at most this many. A shell that finds the page full
# collects again, so this bounds a single burst rather than total throughput.
DEFAULT_COLLECTION_LIMIT = 20


@dataclass(frozen=True)
class PendingDesktopNotifications:
    notifications: list[DesktopNotification]
    has_more: bool


class CollectDesktopNotificationsUseCase:
    def __init__(
        self,
        repo: DesktopNotificationRepository,
        clock: Callable[[], datetime] = utcnow,
        max_age: timedelta = DEFAULT_MAX_AGE,
    ):
        self.repo = repo
        self.clock = clock
        self.max_age = max_age

    def execute(self, user_id: int, limit: int = DEFAULT_COLLECTION_LIMIT) -> PendingDesktopNotifications:
        # One extra row is requested so a full page can be distinguished from a
        # page that merely happens to be exactly `limit` long. The extra row is
        # dropped before returning — it is a lookahead, not a result.
        rows = self.repo.list_pending(user_id, self.clock() - self.max_age, limit + 1)
        return PendingDesktopNotifications(
            notifications=rows[:limit],
            has_more=len(rows) > limit,
        )


class AcknowledgeDesktopNotificationsUseCase:
    """Mark notifications as collected. Returns how many rows actually moved.

    Scoped by user so acknowledging cannot reach another account's rows, and
    idempotent so the repeated OS callbacks issue #88 will introduce are
    harmless: the second call moves nothing and reports 0.
    """

    def __init__(self, repo: DesktopNotificationRepository):
        self.repo = repo

    def execute(self, user_id: int, notification_ids: list[int]) -> int:
        return self.repo.mark_delivered(user_id, notification_ids)


@dataclass(frozen=True)
class ActionOutcome:
    """What happened, and what the shell should do about it."""

    action: NotificationAction
    # False when this notification had already been answered. The action that
    # stands is the first one; this call changed nothing.
    applied: bool
    # True when the shell should bring the review UI forward. Set only on the
    # call that actually applied, so a duplicate OS callback does not reopen a
    # window the user has since closed.
    open_review: bool = False


class PerformNotificationActionUseCase:
    """Carry out one action from a delivered notification.

    Idempotent by construction. The operating system is explicitly allowed to
    deliver the same activation more than once — a click racing a restart, a
    notification-centre replay — so the *first* action recorded is the one that
    stands, and every later call reports it without repeating its effect. The
    effect runs only when the recording actually won, which is what keeps a
    duplicate harmless rather than merely tolerated.

    Expiry is checked before anything is recorded. A toast can sit in a tray
    for days, and "start a five-minute session" answered on Thursday for
    Tuesday's prompt is not what the user was asked.
    """

    def __init__(
        self,
        notifications: DesktopNotificationRepository,
        clock: Callable[[], datetime] = utcnow,
        remind_later_delay: timedelta = REMIND_LATER_DELAY,
    ):
        self.notifications = notifications
        self.clock = clock
        self.remind_later_delay = remind_later_delay

    def execute(
        self, user_id: int, notification_id: int, action: NotificationAction
    ) -> ActionOutcome:
        notification = self.notifications.get_owned(user_id, notification_id)
        if notification is None:
            raise EntityNotFoundError("DesktopNotification", notification_id)
        if notification.is_expired(self.clock()):
            raise NotificationExpiredError("This notification is no longer actionable")

        already_answered = notification.acted_on
        recorded = self.notifications.record_action(user_id, notification_id, action.value)
        applied = not already_answered
        if applied:
            self._apply(user_id, notification, action)

        # The action that stands — for a duplicate that is the original one,
        # not the one this call asked for.
        standing = NotificationAction(recorded) if recorded else action
        return ActionOutcome(
            action=standing,
            applied=applied,
            open_review=applied and standing is NotificationAction.START_SESSION,
        )

    def _apply(
        self, user_id: int, notification: DesktopNotification, action: NotificationAction
    ) -> None:
        if action is NotificationAction.REMIND_LATER:
            self._queue_repeat(user_id, notification)
        elif action is NotificationAction.SKIP_TODAY:
            self._skip_today(user_id, notification)
        # START_SESSION changes nothing server-side. The session it opens is
        # created by the review endpoints when the user actually answers a
        # word; creating one here would leave an empty session behind every
        # time someone clicked and then walked away.

    def _queue_repeat(self, user_id: int, notification: DesktopNotification) -> None:
        """Re-queue the same prompt a little later.

        A new row rather than moving this one: the original was already shown,
        and its acknowledgement is what stops it being shown again. The repeat
        carries its own expiry, so snoozing repeatedly cannot extend one
        notification's life indefinitely.
        """
        due_at = self.clock() + self.remind_later_delay
        self.notifications.add(
            DesktopNotification(
                id=None,
                user_id=user_id,
                message=notification.message,
                created_at=due_at,
                reminder_id=notification.reminder_id,
                expires_at=due_at + NOTIFICATION_ACTION_TTL,
            )
        )

    def _skip_today(self, user_id: int, notification: DesktopNotification) -> None:
        """Drop the rest of today's prompts from the same reminder.

        That means anything still uncollected for this reminder — most usefully
        the repeats a previous "remind me later" queued. Nothing is disabled:
        tomorrow's occurrence is scheduled independently and fires normally,
        which is what "skip today" says rather than "turn this off".
        """
        if notification.reminder_id is not None:
            self.notifications.dismiss_pending_for_reminder(user_id, notification.reminder_id)
