"""Persisted bounded companion-loop budgets (issue #195, TODO 2).

`apps/mcp/lensword_mcp/companion_workflows.py` already enforces
`CompanionLoopBudget`/`CompanionLoopState` correctly, but only in one
process's memory. A companion workflow that spans multiple MCP tool calls
(and therefore, on the stdio transport, potentially multiple server
process lifetimes) needs that same budget to be real, durable state
rather than something that resets whenever the MCP process restarts.

This module is the backend-side mirror of that same policy: same fields,
same defaults, same reservation semantics, plus explicit stop reasons the
issue calls for that the in-memory version does not need (repeated
failure, capability loss, cancellation, unresolved consent). It has zero
I/O, exactly like every other pure domain service in this package —
persistence is a repository's job, not this class's.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LoopLimitReached(RuntimeError):
    """Raised when a reservation would exceed the persisted budget, or the
    loop was already stopped for any reason."""


class LoopStopReason(StrEnum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    REPEATED_FAILURE = "repeated_failure"
    CAPABILITY_LOSS = "capability_loss"
    CANCELLED = "cancelled"
    UNRESOLVED_CONSENT = "unresolved_consent"


# Explicit, caller-chosen stop reasons (as opposed to BUDGET_EXHAUSTED, which
# `reserve` decides on its own). `/stop` only accepts these.
_EXPLICIT_STOP_REASONS = frozenset(
    {
        LoopStopReason.REPEATED_FAILURE,
        LoopStopReason.CAPABILITY_LOSS,
        LoopStopReason.CANCELLED,
        LoopStopReason.UNRESOLVED_CONSENT,
    }
)

_COUNTER_FIELDS = ("tool_calls", "samples", "generated_tokens", "activities", "writes")

_KIND_TO_COUNTER = {
    "tool": "tool_calls",
    "sample": "samples",
    "token": "generated_tokens",
    "activity": "activities",
    "write": "writes",
}


@dataclass(frozen=True)
class CompanionLoopBudget:
    """Hard limits for one workflow; defaults match the in-process budget
    in `apps/mcp/lensword_mcp/companion_workflows.py` so a workflow is
    bounded the same way regardless of which side is holding the counters
    at a given moment."""

    tool_calls: int = 8
    samples: int = 3
    elapsed_seconds: float = 300.0
    generated_tokens: int = 2_000
    activities: int = 10
    writes: int = 10

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.__dict__.values()):
            raise ValueError("workflow budgets cannot be negative")


@dataclass
class CompanionLoopState:
    """Explicit, durable progress state for one session's bounded loop.

    Callers persist this through a repository between reservations; no
    progress toward the budget lives only in a model's context or a
    process's memory.
    """

    session_id: str
    user_id: int
    budget: CompanionLoopBudget
    started_at: datetime
    updated_at: datetime
    tool_calls: int = 0
    samples: int = 0
    generated_tokens: int = 0
    activities: int = 0
    writes: int = 0
    consecutive_failures: int = 0
    stopped_reason: str | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.session_id or len(self.session_id) > 64:
            raise ValueError("loop state session id must contain 1-64 characters")
        if self.revision < 1:
            raise ValueError("loop state revision must be positive")

    @property
    def is_stopped(self) -> bool:
        return self.stopped_reason is not None

    def reserve(self, kind: str, amount: int, *, now: datetime) -> None:
        """Reserve `amount` units of `kind` before an external call.

        Raises `LoopLimitReached` (and durably stops the loop) the moment a
        reservation would exceed budget, so a caller never needs a second
        check after this returns successfully.
        """
        if self.stopped_reason is not None:
            raise LoopLimitReached(self.stopped_reason)
        if amount < 1:
            raise ValueError("reservation amount must be positive")
        counter = _KIND_TO_COUNTER.get(kind)
        if counter is None:
            raise ValueError(f"unknown loop budget kind: {kind}")
        elapsed = (now - self.started_at).total_seconds()
        if elapsed >= self.budget.elapsed_seconds:
            self._stop(LoopStopReason.BUDGET_EXHAUSTED, now)
            raise LoopLimitReached(self.stopped_reason)
        limit = getattr(self.budget, counter)
        current = getattr(self, counter)
        if current + amount > limit:
            self._stop(LoopStopReason.BUDGET_EXHAUSTED, now)
            raise LoopLimitReached(self.stopped_reason)
        setattr(self, counter, current + amount)
        self.consecutive_failures = 0
        self._touch(now)

    def record_failure(self, now: datetime, *, max_consecutive: int = 3) -> None:
        """Track a failed external call. Repeated failure is an explicit
        stop condition (#195 TODO 2), not just a budget line item."""
        if self.stopped_reason is not None:
            return
        self.consecutive_failures += 1
        self._touch(now)
        if self.consecutive_failures >= max_consecutive:
            self._stop(LoopStopReason.REPEATED_FAILURE, now)

    def stop(self, reason: LoopStopReason, now: datetime) -> None:
        """Explicitly stop the loop for a reason the caller decided, not
        one this state computed on its own (capability loss, cancellation,
        or unresolved consent)."""
        if reason not in _EXPLICIT_STOP_REASONS:
            raise ValueError(f"{reason} is not an explicit stop reason")
        self._stop(reason, now)

    def _stop(self, reason: LoopStopReason, now: datetime) -> None:
        if self.stopped_reason is None:
            self.stopped_reason = reason.value
        self._touch(now)

    def _touch(self, now: datetime) -> None:
        self.updated_at = now
        self.revision += 1
