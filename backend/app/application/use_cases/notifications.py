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
from app.domain.repositories import DesktopNotificationRepository
from app.domain.value_objects import utcnow

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
