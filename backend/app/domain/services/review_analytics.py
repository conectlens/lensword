"""What the review schedule is about to demand of a learner (issue #141).

Three questions a dashboard can answer from the schedule alone, without a
model and without guessing:

- **How much do I still remember?** Averaged retrievability across the deck.
- **What is coming?** Reviews due per day over the next fortnight — the
  number that tells someone whether tomorrow is ten minutes or ninety.
- **When should I study?** Deferred to the engagement recommender (#89),
  which already answers this from real behaviour. Not re-derived here, because
  two systems answering the same question differently is worse than one.

The workload forecast is the useful one and the easy one to get wrong.
Spaced repetition front-loads: a learner who adds fifty words today faces
fifty reviews tomorrow, then a trough, then a lump. Showing an average would
hide exactly the spike that makes people quit.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# How far ahead the forecast runs. Two weeks is far enough to show the shape of
# a spike and near enough that the numbers are still real — beyond it every
# figure depends on reviews that have not happened.
FORECAST_DAYS = 14

# Below this, a word is treated as at risk of being forgotten. FSRS schedules
# toward 0.9, so a word materially under that is overdue in substance even if
# its due date has not arrived.
AT_RISK_RETRIEVABILITY = 0.7


@dataclass(frozen=True)
class DayForecast:
    on: date
    due_count: int


@dataclass
class ReviewAnalytics:
    total_words: int = 0
    # Mean retrievability across words that have been reviewed at least once.
    # Unreviewed words are excluded rather than counted as zero, which would
    # make a deck of new words look like catastrophic memory loss.
    average_retention: float | None = None
    at_risk_count: int = 0
    due_now: int = 0
    forecast: list[DayForecast] = field(default_factory=list)

    @property
    def busiest_day(self) -> DayForecast | None:
        """The spike. This is what a learner actually needs to see — an average
        would hide the day that makes them quit."""
        return max(self.forecast, key=lambda d: d.due_count, default=None)


@dataclass(frozen=True)
class ScheduledWord:
    """The scheduling facts one word contributes. Passed in rather than
    queried, so the whole calculation is testable at a fixed instant."""

    due_at: datetime | None
    retrievability: float | None


def build_analytics(
    words: list[ScheduledWord], now: datetime, horizon_days: int = FORECAST_DAYS
) -> ReviewAnalytics:
    if not words:
        return ReviewAnalytics()

    reviewed = [w.retrievability for w in words if w.retrievability is not None]
    due_now = sum(1 for w in words if w.due_at is not None and w.due_at <= now)

    counts: Counter[date] = Counter()
    today = now.date()
    for word in words:
        if word.due_at is None:
            continue
        # Anything already due is counted as today's work rather than given a
        # date in the past. A forecast row for last Tuesday is not a forecast.
        when = max(word.due_at.date(), today)
        if (when - today).days < horizon_days:
            counts[when] += 1

    # Every day in the window appears, including empty ones. A forecast that
    # omits quiet days compresses the axis and makes a spike look like a
    # gentle slope.
    forecast = [
        DayForecast(on=today + timedelta(days=offset), due_count=counts.get(today + timedelta(days=offset), 0))
        for offset in range(horizon_days)
    ]

    return ReviewAnalytics(
        total_words=len(words),
        average_retention=round(sum(reviewed) / len(reviewed), 4) if reviewed else None,
        at_risk_count=sum(1 for r in reviewed if r < AT_RISK_RETRIEVABILITY),
        due_now=due_now,
        forecast=forecast,
    )
