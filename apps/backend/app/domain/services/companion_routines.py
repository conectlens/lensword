"""Bounded, factual companion routines (#197 TODO 4).

Every function here is pure and I/O-free, deterministic under test: callers
(a router, an MCP tool) are responsible for gathering the facts — due counts,
efficacy estimates, inactivity — from the repositories that already own
them, and pass them in. Nothing here invents a fact, and nothing here is a
new source of truth; it only assembles what's already known into a bounded,
reviewable shape, the same discipline `conversation_context`-style fact
assembly and `intervention_efficacy.py`'s sample-size discipline already
established elsewhere in the companion epic.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.services.intervention_efficacy import EfficacyEstimate, EfficacyStatus

# Below this many consecutive inactive days, "welcome back" framing would be
# noise — a two-day gap over a weekend is not the kind of absence a recovery
# routine should comment on at all.
RECOVERY_INACTIVITY_THRESHOLD_DAYS = 5

# A companion routine is a handful of facts, not a report: both routines
# below refuse to describe more than this many due words or measured
# interventions individually, falling back to a count instead.
MAX_HEADLINE_ITEMS = 5


@dataclass(frozen=True)
class DailyCheckIn:
    due_count: int
    goal_minutes: int | None
    headline: str


def build_daily_check_in(due_count: int, goal_minutes: int | None = None) -> DailyCheckIn:
    """A bounded, factual summary of what's due today — no streaks, no guilt.

    `due_count` is trusted verbatim from the caller (typically the same due-
    word count `DeliverReminderUseCase` already computes), never re-derived
    or estimated here.
    """
    if due_count < 0:
        raise ValueError("due_count cannot be negative")
    if goal_minutes is not None and goal_minutes < 1:
        raise ValueError("goal_minutes must be positive when given")
    if due_count == 0:
        headline = "No words are due today."
    elif due_count == 1:
        headline = "One word is due today."
    else:
        headline = f"{due_count} words are due today."
    return DailyCheckIn(due_count=due_count, goal_minutes=goal_minutes, headline=headline)


@dataclass(frozen=True)
class WeeklyReflection:
    measured: tuple[EfficacyEstimate, ...]
    insufficient_evidence_count: int
    headline: str


def build_weekly_reflection(estimates: list[EfficacyEstimate]) -> WeeklyReflection:
    """A weekly reflection that never states an effect without its sample.

    Mirrors `intervention_efficacy.py`'s own abstention-first discipline: an
    estimate whose status is not MEASURED contributes to a count, never to a
    claim. `EfficacyEstimate.recommendation` already refuses to produce text
    for anything but MEASURED, so this function does not have to re-check
    that — it would simply have nothing to say for the rest.
    """
    measured = tuple(e for e in estimates if e.status is EfficacyStatus.MEASURED)
    insufficient = sum(1 for e in estimates if e.status is not EfficacyStatus.MEASURED)
    if not measured:
        headline = (
            "Not enough delayed-recall evidence yet this week to measure any intervention."
            if insufficient
            else "No interventions were evaluated this week."
        )
    else:
        shown = measured[:MAX_HEADLINE_ITEMS]
        parts = [
            f"{estimate.intervention_type} ({estimate.intervention_samples} samples): "
            f"{estimate.effect:+.1%}"
            for estimate in shown
        ]
        headline = "; ".join(parts)
        if len(measured) > MAX_HEADLINE_ITEMS:
            headline += f"; and {len(measured) - MAX_HEADLINE_ITEMS} more"
    return WeeklyReflection(measured=measured, insufficient_evidence_count=insufficient, headline=headline)


@dataclass(frozen=True)
class RecoveryRoutine:
    days_inactive: int
    due_count: int
    headline: str
    suggested_minutes: int


def build_recovery_routine(days_inactive: int, due_count: int) -> RecoveryRoutine:
    """A neutral, non-guilt-based re-entry after a gap.

    Deliberately avoids "you've fallen behind", "you missed", streak
    language, or any framing that treats the gap as a failure — the routine
    states what's true (days since the last session, what's due now) and
    proposes a small, achievable next step, nothing more.
    """
    if days_inactive < 0:
        raise ValueError("days_inactive cannot be negative")
    if due_count < 0:
        raise ValueError("due_count cannot be negative")
    if days_inactive < RECOVERY_INACTIVITY_THRESHOLD_DAYS:
        headline = "Ready to continue."
    else:
        headline = "Welcome back. Here's what's waiting whenever you're ready."
    # A short, bounded first step regardless of how much has piled up — the
    # point of a recovery routine is a low-friction re-entry, not clearing
    # the whole backlog in one sitting.
    suggested_minutes = 5 if due_count > 0 else 0
    return RecoveryRoutine(
        days_inactive=days_inactive,
        due_count=due_count,
        headline=headline,
        suggested_minutes=suggested_minutes,
    )


@dataclass(frozen=True)
class MicroSessionPlan:
    word_ids: tuple[int, ...]
    estimated_minutes: int


def build_micro_session_plan(due_word_ids: list[int], minutes_available: int) -> MicroSessionPlan:
    """A bounded activity plan sized to the time the learner actually has.

    One word per minute is a deliberately conservative, easy-to-explain
    estimate — this is a bound, not a claim about how long any given word
    will take; `companion_task_execution.plan_micro_session_units` is what
    actually turns a selection like this into real activities.
    """
    if minutes_available < 1:
        raise ValueError("minutes_available must be positive")
    word_count = min(len(due_word_ids), minutes_available)
    return MicroSessionPlan(word_ids=tuple(due_word_ids[:word_count]), estimated_minutes=word_count)
