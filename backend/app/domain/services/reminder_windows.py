"""Recommend a better reminder time from real engagement (issue #89).

The point of this service is what it refuses to do. It never changes a
schedule, never sends anything, and produces no recommendation at all unless
the evidence clears a stated bar — because the failure mode worth designing
against is not a mediocre suggestion, it is a system that quietly moves
someone's reminders and cannot say why.

So: pure, deterministic, and explainable. The same history always yields the
same answer, every recommendation carries the counts it was derived from, and
acceptance is the user's (see AcceptReminderWindowUseCase). A model may later
phrase the explanation, but the numbers in it come from here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time

from app.domain.value_objects import NotificationAction

# Below this, a recommendation is noise dressed as insight. Three engagements
# in one hour-slot is not evidence that the slot is better — it is evidence
# that someone was awake twice.
MIN_TOTAL_DELIVERIES = 10
MIN_DELIVERIES_PER_SLOT = 4

# A slot has to beat the current time by this much before it is worth asking
# the user about. Without a margin, a 52%-vs-48% split would generate a prompt
# every week, and reminders that keep moving are worse than reminders at a
# mediocre hour.
MIN_IMPROVEMENT = 0.15


@dataclass(frozen=True)
class EngagementEvent:
    """One delivered notification and what became of it.

    `local_hour` is the hour on the *user's* clock, resolved by the caller.
    Bucketing on UTC would recommend 07:00 to someone who engages at 09:00
    from three time zones away, and would move the recommendation whenever
    they travelled.
    """

    local_hour: int
    action: str | None


@dataclass(frozen=True)
class WindowRecommendation:
    """A suggested hour, and everything needed to justify it."""

    hour: int
    # Engagement rate in the suggested slot and in the current one, as
    # fractions. Carried rather than a single "confidence" score so the
    # explanation can state both instead of asserting a verdict.
    suggested_rate: float
    current_rate: float
    suggested_sample: int
    current_sample: int

    @property
    def improvement(self) -> float:
        return self.suggested_rate - self.current_rate

    def explain(self) -> str:
        """Plain-language justification, built from the counts alone.

        Deliberately not generated: the user is being asked to change when they
        are interrupted, and the reason has to be checkable against the data
        rather than plausible-sounding.
        """
        return (
            f"You started a review after {self.suggested_rate:.0%} of reminders "
            f"at {self.hour:02d}:00 ({self.suggested_sample} reminders), "
            f"compared with {self.current_rate:.0%} at your current time "
            f"({self.current_sample} reminders)."
        )


def _engaged(event: EngagementEvent) -> bool:
    """Whether the user acted on the reminder rather than deferring it.

    Only starting a session counts. Snoozing and skipping are explicit
    deferrals, and no action at all is the commonest outcome of a badly-timed
    reminder — treating either as neutral would let a slot look good precisely
    because it was ignored quietly.
    """
    return event.action == NotificationAction.START_SESSION.value


class ReminderWindowRecommender:
    """Stateless domain service. Given a history and the current trigger time,
    suggest a better hour or say nothing."""

    @staticmethod
    def recommend(
        events: list[EngagementEvent],
        current_time: time,
        allowed_hours: set[int],
        min_total: int = MIN_TOTAL_DELIVERIES,
        min_per_slot: int = MIN_DELIVERIES_PER_SLOT,
        min_improvement: float = MIN_IMPROVEMENT,
    ) -> WindowRecommendation | None:
        """Return the best supportable suggestion, or None.

        `allowed_hours` is the set the caller has already filtered for quiet
        hours, caps and Do Not Disturb. Passing it in rather than deriving it
        here keeps this service free of settings, and means a slot the user has
        forbidden cannot be recommended even if the data loves it.
        """
        if len(events) < min_total or not allowed_hours:
            return None

        by_hour: dict[int, list[EngagementEvent]] = defaultdict(list)
        for event in events:
            by_hour[event.local_hour].append(event)

        current = by_hour.get(current_time.hour, [])
        current_rate = _rate(current)

        best: WindowRecommendation | None = None
        # Sorted so ties resolve to the earliest hour rather than to whatever
        # order the dictionary happened to have. Determinism is a stated
        # requirement: the same history must always give the same answer.
        for hour in sorted(allowed_hours):
            if hour == current_time.hour:
                continue
            slot = by_hour.get(hour, [])
            if len(slot) < min_per_slot:
                continue
            rate = _rate(slot)
            if rate - current_rate < min_improvement:
                continue
            if best is not None and rate <= best.suggested_rate:
                continue
            best = WindowRecommendation(
                hour=hour,
                suggested_rate=rate,
                current_rate=current_rate,
                suggested_sample=len(slot),
                current_sample=len(current),
            )
        return best


def _rate(events: list[EngagementEvent]) -> float:
    if not events:
        return 0.0
    return sum(1 for e in events if _engaged(e)) / len(events)
