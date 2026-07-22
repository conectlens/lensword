"""NotificationChannel port (hexagonal-architecture sense).

Structural typing.Protocol, matching app.domain.repositories: adapters don't
need to inherit from anything domain-related. Dispatching notifications on a
schedule (Phase 2) is not implemented here — this is only the interface and
one concrete adapter, per ROADMAP.md Phase 0.1.
"""
from __future__ import annotations

from typing import Protocol

from app.domain.entities import User


class NotificationChannel(Protocol):
    def send(self, user: User, message: str, channel: str) -> None: ...
