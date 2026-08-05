"""ReminderScheduler port (hexagonal-architecture sense).

Registering background jobs is infrastructure, but *deciding* that a reminder
should have one is application policy — so the use cases depend on this
Protocol and never on APScheduler. Structural typing.Protocol, matching
app.domain.repositories: adapters inherit from nothing domain-related.
"""
from __future__ import annotations

from typing import Protocol

from app.domain.entities import Reminder


class ReminderScheduler(Protocol):
    """`time_zone` is passed in rather than read off the reminder.

    A reminder carries a `user_id`, not a user, so an adapter could not reach
    the owner's zone without acquiring a repository of its own. Callers
    already hold the user. The alternative — copying the zone onto every
    reminder row — would duplicate a user-level property per reminder and
    leave stale copies behind the moment the user changes it (issue #44).
    """

    def schedule(self, reminder: Reminder, time_zone: str) -> None: ...
    def unschedule(self, reminder_id: int) -> None: ...
