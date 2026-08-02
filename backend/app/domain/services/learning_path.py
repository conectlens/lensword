"""Turning a stated goal into milestones, and measuring them (issue #137).

"I want to order food in Spain" is a goal. A path is that goal broken into
things a learner can tell they have done. The gap between the two is where this
feature either helps or produces a motivational poster.

Two rules keep it honest.

**Progress is measured, never stored.** A milestone is complete when the
learner actually holds the vocabulary it names — counted from their deck at
read time. A stored percentage is a number that was true once; it drifts the
moment a word is added or deleted, and a progress bar that disagrees with the
vocabulary list is worse than no progress bar.

**A model's plan is a suggestion that must survive validation.** Asked for
milestones, a model will sometimes return sixty of them, or one with an empty
title, or a target of five thousand words. Those are not paths. The plan is
bounded and cleaned here before it is ever stored, because a path is shown to
the learner as advice and unbounded advice is how people conclude the product
does not know what it is talking about.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A path longer than this stops being a plan and becomes a syllabus nobody
# opens. Models asked for "a learning path" happily return thirty steps.
MAX_MILESTONES = 8

# Fewer than this is not a path, it is a single task with extra formatting.
MIN_MILESTONES = 2

# Vocabulary a single milestone can ask for. Generous at the top so a serious
# goal is not flattened, bounded so a model cannot set a target nobody reaches.
MAX_WORDS_PER_MILESTONE = 60
MIN_WORDS_PER_MILESTONE = 3

MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 400
MAX_GOAL_CHARS = 500


class InvalidPlanError(ValueError):
    """The model's plan could not be made into a path."""


@dataclass(frozen=True)
class MilestonePlan:
    """One step, as proposed before it is stored."""

    title: str
    description: str
    # The vocabulary topic this step is about. Matched against the learner's
    # own word topics to measure progress, which is why it is a single tag
    # rather than prose.
    topic: str
    target_word_count: int
    cefr_level: str | None = None


@dataclass(frozen=True)
class MilestoneProgress:
    """A milestone with the learner's actual standing against it."""

    position: int
    title: str
    description: str
    topic: str
    target_word_count: int
    cefr_level: str | None
    # Words the learner holds on this topic. Counted at read time from their
    # deck — never stored, because a stored count is a number that was true
    # once.
    words_held: int
    words_mastered: int

    @property
    def complete(self) -> bool:
        return self.words_held >= self.target_word_count

    @property
    def share(self) -> float:
        if self.target_word_count <= 0:
            return 0.0
        # Capped at 1.0: a learner who added twice the target has finished the
        # milestone, not finished it twice.
        return round(min(self.words_held / self.target_word_count, 1.0), 4)


@dataclass
class PathProgress:
    goal: str
    milestones: list[MilestoneProgress] = field(default_factory=list)

    @property
    def completed_count(self) -> int:
        return sum(1 for milestone in self.milestones if milestone.complete)

    @property
    def share(self) -> float:
        """Overall progress, by milestone rather than by word.

        A path with one huge step and four small ones should not read as 80%
        done when the big one is untouched — but neither should a learner be
        told they are 4% along because one milestone happens to be enormous.
        Milestones are the unit the learner sees, so they are the unit counted.
        """
        if not self.milestones:
            return 0.0
        return round(self.completed_count / len(self.milestones), 4)

    @property
    def next_milestone(self) -> MilestoneProgress | None:
        """The first unfinished step. What the learner is actually asked to do."""
        return next((m for m in self.milestones if not m.complete), None)


def validate_plan(raw: list[dict]) -> list[MilestonePlan]:
    """Clean and bound a model's proposed milestones.

    Raises rather than silently returning a shorter path when nothing usable
    survives: an empty path presented as a plan is worse than an error, because
    the learner cannot tell whether it means "no steps needed" or "this went
    wrong".
    """
    plans: list[MilestonePlan] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        title = _clean(entry.get("title"), MAX_TITLE_CHARS)
        topic = _clean(entry.get("topic"), 64)
        if not title or not topic:
            # A step with no title is not something a learner can act on, and
            # one with no topic cannot be measured — both are dropped rather
            # than shown as an empty card.
            continue

        plans.append(
            MilestonePlan(
                title=title,
                description=_clean(entry.get("description"), MAX_DESCRIPTION_CHARS) or "",
                topic=topic,
                target_word_count=_bounded_count(entry.get("target_word_count")),
                cefr_level=_clean_level(entry.get("cefr_level")),
            )
        )
        if len(plans) == MAX_MILESTONES:
            break

    if len(plans) < MIN_MILESTONES:
        raise InvalidPlanError(
            "The model did not return a usable plan. Try rephrasing the goal."
        )
    return plans


def clean_goal(goal: str) -> str:
    """Normalise the learner's stated goal.

    Bounded because it is stored, displayed, and sent to a model. An
    unbounded goal is a way to push everything else out of a prompt.
    """
    cleaned = " ".join((goal or "").split())
    if not cleaned:
        raise InvalidPlanError("A goal is required")
    return cleaned[:MAX_GOAL_CHARS]


def measure(
    goal: str,
    milestones: list[MilestonePlan],
    words_by_topic: dict[str, tuple[int, int]],
) -> PathProgress:
    """Score each milestone against the learner's vocabulary.

    `words_by_topic` maps a lowercased topic to (held, mastered). Passed in
    rather than queried here so this stays pure — and so the caller decides
    what "mastered" means once, rather than this module inventing a second
    definition of it.
    """
    scored = []
    for index, milestone in enumerate(milestones):
        held, mastered = words_by_topic.get(milestone.topic.strip().casefold(), (0, 0))
        scored.append(
            MilestoneProgress(
                position=index,
                title=milestone.title,
                description=milestone.description,
                topic=milestone.topic,
                target_word_count=milestone.target_word_count,
                cefr_level=milestone.cefr_level,
                words_held=held,
                words_mastered=mastered,
            )
        )
    return PathProgress(goal=goal, milestones=scored)


def _clean(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _clean_level(value) -> str | None:
    if not isinstance(value, str):
        return None
    level = value.strip().upper()
    # An unrecognised level is dropped rather than stored. "Intermediate" is
    # not a CEFR level, and keeping it would put a value in the column that
    # nothing else in the system can compare against.
    return level if level in {"A1", "A2", "B1", "B2", "C1", "C2"} else None


def _bounded_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        # A missing or unparseable target becomes the floor rather than zero.
        # Zero would make the milestone complete the moment it is created.
        return MIN_WORDS_PER_MILESTONE
    return max(MIN_WORDS_PER_MILESTONE, min(count, MAX_WORDS_PER_MILESTONE))
