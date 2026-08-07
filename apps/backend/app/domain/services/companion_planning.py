"""Bounded companion session activity planning (#194 TODO 4).

Deterministic and pure: given the same `ConversationContext` facts (#194
TODO 2), `generate_activity_plan` always produces the same plan. There is no
open-ended agent loop, no tool-calling search, and no AI call here — a
single capped pass over already-bounded due items and active words, ranking
confusion-backed due items first because that is the single highest-value
thing this planner can suggest from deterministic evidence alone.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.services.companion_activities import ActivityType
from app.domain.services.conversation_context import ConversationContext

# A plan can never propose more activities than this, regardless of how
# many due items or active words the context contains.
MAX_PLANNED_ACTIVITIES = 8

# Duration/tool-call/write budgets are derived per planned activity and
# capped in total — the plan carries its own bounded execution envelope
# rather than leaving a caller to guess a safe one.
_SECONDS_PER_ACTIVITY = 180
MAX_PLAN_DURATION_SECONDS = 1800
_TOOL_CALLS_PER_ACTIVITY = 3
_WRITES_PER_ACTIVITY = 1


@dataclass(frozen=True, slots=True)
class PlannedActivity:
    activity_type: ActivityType
    word_id: int
    term: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "activity_type": self.activity_type.value,
            "word_id": self.word_id,
            "term": self.term,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class ActivityPlan:
    """A small, ordered set of suggested activities plus the bounded budget
    executing all of them is allowed to spend. `confirmed` always starts
    `False` here — nothing in this module can set it `True`; only an
    explicit, separate confirmation step one layer up may do that (#194
    TODO 4's "require confirmation before any plan that would write
    observations or cards actually starts executing").
    """

    session_id: str
    items: tuple[PlannedActivity, ...]
    max_duration_seconds: int
    max_tool_calls: int
    max_writes: int
    confirmed: bool = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "items": [item.to_dict() for item in self.items],
            "max_duration_seconds": self.max_duration_seconds,
            "max_tool_calls": self.max_tool_calls,
            "max_writes": self.max_writes,
            "confirmed": self.confirmed,
        }


def generate_activity_plan(context: ConversationContext, *, max_activities: int = 5) -> ActivityPlan:
    capped = max(1, min(max_activities, MAX_PLANNED_ACTIVITIES))
    confused_word_ids = {fact.word_id for fact in context.confusion}
    items: list[PlannedActivity] = []
    seen: set[int] = set()

    def _take(word_id: int, term: str, activity_type: ActivityType, rationale: str) -> bool:
        if word_id in seen or len(items) >= capped:
            return False
        items.append(PlannedActivity(activity_type=activity_type, word_id=word_id, term=term, rationale=rationale))
        seen.add(word_id)
        return len(items) >= capped

    # Confusion-backed due items lead the plan.
    for due in context.due_items:
        if due.word_id in confused_word_ids:
            if _take(
                due.word_id, due.term, ActivityType.RECALL,
                "Due for review and recently flagged as confusing by evidence-backed diagnosis.",
            ):
                return _finish(context.session_id, items)

    # Then the rest of what is due.
    for due in context.due_items:
        if _take(due.word_id, due.term, ActivityType.RECALL, "Due for review."):
            return _finish(context.session_id, items)

    # Then active words not already covered, as lighter cloze practice.
    for active in context.active_words:
        if _take(active.word_id, active.term, ActivityType.CLOZE, "Currently active vocabulary, not yet due."):
            break

    return _finish(context.session_id, items)


def _finish(session_id: str, items: list[PlannedActivity]) -> ActivityPlan:
    count = len(items)
    return ActivityPlan(
        session_id=session_id,
        items=tuple(items),
        max_duration_seconds=min(MAX_PLAN_DURATION_SECONDS, max(_SECONDS_PER_ACTIVITY, count * _SECONDS_PER_ACTIVITY)),
        max_tool_calls=count * _TOOL_CALLS_PER_ACTIVITY,
        max_writes=count * _WRITES_PER_ACTIVITY,
        confirmed=False,
    )


def plan_from_dict(payload: dict) -> ActivityPlan:
    """Reconstruct a plan previously serialized by `ActivityPlan.to_dict`
    (stored as a `CompanionTask.result`) — used only to re-hydrate a plan
    for confirmation, never to accept an arbitrary caller-supplied plan
    shape as if it had been generated."""
    items = tuple(
        PlannedActivity(
            activity_type=ActivityType(item["activity_type"]),
            word_id=int(item["word_id"]),
            term=str(item["term"]),
            rationale=str(item["rationale"]),
        )
        for item in payload.get("items", [])
    )
    return ActivityPlan(
        session_id=str(payload["session_id"]),
        items=items,
        max_duration_seconds=int(payload["max_duration_seconds"]),
        max_tool_calls=int(payload["max_tool_calls"]),
        max_writes=int(payload["max_writes"]),
        confirmed=bool(payload.get("confirmed", False)),
    )
