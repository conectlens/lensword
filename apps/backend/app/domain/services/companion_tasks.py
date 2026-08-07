"""Bounded durable companion task state (#197).

Tasks are explicit application state, not unsolicited messages or hidden model
memory.  The task owner controls cancellation and only completed work units
may advance progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class CompanionTaskType(StrEnum):
    EXTRACTION = "extraction"
    PLAN_GENERATION = "plan_generation"
    SESSION_PREPARATION = "session_preparation"


class CompanionTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


_TERMINAL = frozenset(
    {
        CompanionTaskStatus.COMPLETED,
        CompanionTaskStatus.CANCELLED,
        CompanionTaskStatus.FAILED,
        CompanionTaskStatus.EXPIRED,
    }
)


@dataclass
class CompanionTask:
    id: str
    session_id: str
    user_id: int
    task_type: CompanionTaskType
    status: CompanionTaskStatus
    total_units: int
    completed_units: int
    result: dict[str, Any] | None
    error: str | None
    operation_id: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.id or len(self.id) > 64:
            raise ValueError("task id must contain 1-64 characters")
        if not self.session_id or len(self.session_id) > 64:
            raise ValueError("session id must contain 1-64 characters")
        if self.total_units < 1 or self.total_units > 10_000:
            raise ValueError("task total_units must be between 1 and 10000")
        if not 0 <= self.completed_units <= self.total_units:
            raise ValueError("completed_units must be within total_units")
        if self.revision < 1:
            raise ValueError("task revision must be positive")
        if self.operation_id is not None and len(self.operation_id) > 128:
            raise ValueError("task operation_id is limited to 128 characters")
        if self.error is not None and len(self.error) > 500:
            raise ValueError("task errors are limited to 500 characters")

    @property
    def progress(self) -> float:
        return self.completed_units / self.total_units

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def start(self, now: datetime) -> None:
        if self.status is CompanionTaskStatus.PENDING:
            self.status = CompanionTaskStatus.RUNNING
            self._touch(now)
            return
        if self.status is CompanionTaskStatus.RUNNING:
            return
        raise ValueError("terminal companion tasks cannot be started")

    def update_progress(self, completed_units: int, now: datetime) -> None:
        if self.status is CompanionTaskStatus.PENDING:
            self.start(now)
        if self.status is not CompanionTaskStatus.RUNNING:
            raise ValueError("only running companion tasks accept progress")
        if completed_units < self.completed_units:
            raise ValueError("task progress cannot move backwards")
        if completed_units > self.total_units:
            raise ValueError("task progress cannot exceed total_units")
        self.completed_units = completed_units
        self._touch(now)

    def complete(self, result: dict[str, Any] | None, now: datetime) -> None:
        if self.status is CompanionTaskStatus.PENDING:
            self.start(now)
        if self.status is not CompanionTaskStatus.RUNNING:
            raise ValueError("only running companion tasks can complete")
        self.completed_units = self.total_units
        self.result = dict(result or {})
        self.status = CompanionTaskStatus.COMPLETED
        self._touch(now)

    def cancel(self, now: datetime) -> None:
        if self.status is CompanionTaskStatus.CANCELLED:
            return
        if self.is_terminal:
            raise ValueError("terminal companion tasks cannot be cancelled")
        self.status = CompanionTaskStatus.CANCELLED
        self._touch(now)

    def expire_if_due(self, now: datetime) -> bool:
        if self.is_terminal or now < self.expires_at:
            return False
        self.status = CompanionTaskStatus.EXPIRED
        self._touch(now)
        return True

    def record_plan_confirmation(self, result: dict[str, Any], now: datetime) -> None:
        """Store the outcome of confirming (and, on confirmation, executing)
        a `plan_generation` task's plan (#194 TODO 4).

        Only ever called after `complete` has already stored the generated,
        unconfirmed plan (`status is COMPLETED`) — confirming a plan does
        not reopen the task, it records one more fact about what happened
        to the plan the task already produced. Raises if this task is not a
        `plan_generation` task, has no plan yet, or was already confirmed —
        a plan can be executed at most once.
        """
        if self.task_type is not CompanionTaskType.PLAN_GENERATION:
            raise ValueError("Only a plan_generation task can record a plan confirmation")
        if self.status is not CompanionTaskStatus.COMPLETED:
            raise ValueError("A plan must be generated before it can be confirmed")
        if isinstance(self.result, dict) and self.result.get("confirmed"):
            raise ValueError("This plan has already been confirmed")
        self.result = dict(result)
        self._touch(now)

    def fail(self, error: str, now: datetime) -> None:
        if self.is_terminal:
            raise ValueError("terminal companion tasks cannot fail")
        if not error.strip():
            raise ValueError("task failure reason is required")
        self.error = error[:500]
        self.status = CompanionTaskStatus.FAILED
        self._touch(now)

    def _touch(self, now: datetime) -> None:
        self.updated_at = now
        self.revision += 1
