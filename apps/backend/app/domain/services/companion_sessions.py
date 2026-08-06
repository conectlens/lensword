"""Provider-neutral companion session state (issue #193).

The companion owns conversation style; LensWord owns this normalized state.
Only bounded turns and structured metadata are accepted here. Provider
memory, chain-of-thought, credentials, and opaque tool state have no field in
the model and therefore cannot be persisted accidentally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CompanionSessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"
    REVOKED = "revoked"


class CompanionTurnRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class CompanionSession:
    id: str
    user_id: int
    connection_id: str
    client_id: str
    goal: str | None
    language: str | None
    group_id: int | None
    difficulty: str | None
    active_activity: str | None
    consent_snapshot: dict
    summary: str | None
    status: CompanionSessionStatus
    revision: int
    created_at: datetime
    updated_at: datetime

    def _transition(self, status: CompanionSessionStatus) -> None:
        if self.status is CompanionSessionStatus.REVOKED:
            raise ValueError("A revoked companion session cannot be resumed")
        if self.status is CompanionSessionStatus.FINISHED and status is not CompanionSessionStatus.REVOKED:
            raise ValueError("A finished companion session cannot be reopened")
        self.status = status
        self.revision += 1

    def resume(self) -> None:
        self._transition(CompanionSessionStatus.ACTIVE)

    def pause(self) -> None:
        self._transition(CompanionSessionStatus.PAUSED)

    def finish(self) -> None:
        self._transition(CompanionSessionStatus.FINISHED)

    def revoke(self) -> None:
        self.status = CompanionSessionStatus.REVOKED
        self.revision += 1

    def update_summary(self, summary: str | None) -> None:
        if summary is not None and len(summary) > 4000:
            raise ValueError("Companion summaries are limited to 4000 characters")
        self.summary = summary
        self.revision += 1


@dataclass(frozen=True, slots=True)
class CompanionTurn:
    id: int | None
    session_id: str
    role: CompanionTurnRole
    content: str
    activity_id: str | None
    operation_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.content.strip() or len(self.content) > 10000:
            raise ValueError("Companion turn content must contain 1-10000 characters")
        if self.operation_id is not None and len(self.operation_id) > 128:
            raise ValueError("Companion operation_id is too long")
