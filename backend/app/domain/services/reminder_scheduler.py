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
    def schedule(self, reminder: Reminder) -> None: ...
    def unschedule(self, reminder_id: int) -> None: ...
