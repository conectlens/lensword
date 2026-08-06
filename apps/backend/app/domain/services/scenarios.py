"""Role-play scenarios and how an attempt is scored (issue #136).

A scenario gives a conversation a *point*: not "chat in Spanish" but "get
through airport security", with things you have to actually accomplish. That
last part is what makes it scoreable — task completion is the one dimension a
free conversation cannot have.

The catalog is a **code constant, not a table.** The issue said "seed a
catalog", and a seeded table was the obvious reading; this is a deliberate
departure. Each scenario carries the goals the evaluator scores against, so
catalog and evaluation have to agree — and a table would let them drift, with
the failure mode being an attempt scored against goals that no longer match the
scenario the learner saw. Nothing in the issue asks for user-authored
scenarios, and a migration plus admin CRUD for seven fixed rows is machinery
serving nobody. If user-authored scenarios are ever wanted, that is a table
with an owner column, which is a different feature.

**An attempt too short to judge is not scored.** Three messages is not evidence
of fluency, and a confident 72/100 derived from one exchange is the same
failure the weakness profile refuses to make: a number the learner will believe
because it looks precise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Turns the learner must contribute before an attempt can be scored. Below it,
# the honest answer is that there is not enough to judge.
MIN_LEARNER_TURNS_TO_SCORE = 4

# Total characters across every learner turn combined — a floor on substance,
# not fluency, kept separate from the turn count above because a turn-count
# check alone cannot tell four one-word non-answers ("queso", "no se", "mmm",
# "banana carro azul" — the exact transcript that produced a fabricated
# 82/100 during issue #166's real-model verification pass) from four short
# but real sentences. Four genuine short exchanges in a restaurant scenario
# ("Hola", "Una mesa para dos, por favor", "Sí, el especial", "Gracias" — 54
# characters) comfortably clear this; four throwaway non-answers (31
# characters) do not (issue #213).
MIN_LEARNER_CHARACTERS_TO_SCORE = 40

# Scores are 0-100 to match the strength scale already used for words, so a
# learner never has to hold two different scales in mind.
MIN_SCORE = 0
MAX_SCORE = 100


class ScoreDimension(str, Enum):
    """What an attempt is judged on.

    Closed and small. Each one has to be something a learner can act on:
    "vocabulary" tells them to learn more words, "fluency" tells them to keep
    going without stalling. A dimension nobody can act on is a number that only
    makes people feel judged.
    """

    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    FLUENCY = "fluency"
    # Whether they actually did the thing the scenario asked. The dimension a
    # free conversation cannot have, and the reason scenarios exist.
    TASK_COMPLETION = "task_completion"


@dataclass(frozen=True)
class Scenario:
    """One situation to practise."""

    key: str
    title: str
    # Shown to the learner before they start. Second person, because they are
    # the one in the situation.
    briefing: str
    # What the tutor plays. Kept separate from the briefing so the learner is
    # never shown the instruction given to the model.
    tutor_role: str
    # Concrete things to accomplish. These are what `TASK_COMPLETION` is scored
    # against, which is why they live beside the scenario rather than being
    # invented per attempt.
    goals: tuple[str, ...]
    suggested_topics: tuple[str, ...] = ()


CATALOG: tuple[Scenario, ...] = (
    Scenario(
        key="job_interview",
        title="Job interview",
        briefing="You are interviewing for a job you want. Introduce yourself, "
        "describe your experience, and ask at least one question about the role.",
        tutor_role="a friendly but thorough hiring manager",
        goals=("Introduce yourself", "Describe your experience", "Ask about the role"),
        suggested_topics=("work", "education"),
    ),
    Scenario(
        key="airport",
        title="At the airport",
        briefing="You are checking in for a flight. Find your gate, ask about "
        "your luggage, and deal with a delay.",
        tutor_role="an airline check-in agent",
        goals=("Check in for your flight", "Ask about luggage", "Handle a delay"),
        suggested_topics=("travel", "transport"),
    ),
    Scenario(
        key="restaurant",
        title="Ordering at a restaurant",
        briefing="You are eating out. Order food and drink, ask about an "
        "ingredient, and ask for the bill.",
        tutor_role="a waiter in a busy restaurant",
        goals=("Order food and drink", "Ask about an ingredient", "Ask for the bill"),
        suggested_topics=("food", "restaurant"),
    ),
    Scenario(
        key="customer_support",
        title="Customer support",
        briefing="Something you bought is faulty. Explain the problem, say what "
        "you want done, and agree on a next step.",
        tutor_role="a polite but cautious support agent",
        goals=("Explain the problem", "Say what you want", "Agree a next step"),
        suggested_topics=("shopping", "technology"),
    ),
    Scenario(
        key="meeting",
        title="Team meeting",
        briefing="You are in a work meeting. Give an update, disagree with "
        "something politely, and agree an action.",
        tutor_role="a colleague chairing the meeting",
        goals=("Give an update", "Disagree politely", "Agree an action"),
        suggested_topics=("work", "business"),
    ),
    Scenario(
        key="presentation",
        title="Giving a presentation",
        briefing="You are presenting an idea. Open, explain your main point, "
        "and answer a question from the audience.",
        tutor_role="an interested audience member who asks questions",
        goals=("Open the presentation", "Explain your main point", "Answer a question"),
        suggested_topics=("work", "business"),
    ),
    Scenario(
        key="travel_emergency",
        title="Travel emergency",
        briefing="You have lost your bag in an unfamiliar city. Explain what "
        "happened, ask for help, and arrange what to do next.",
        tutor_role="a helpful stranger, then a police officer",
        goals=("Explain what happened", "Ask for help", "Arrange what to do next"),
        suggested_topics=("travel", "emergency"),
    ),
)

_BY_KEY = {scenario.key: scenario for scenario in CATALOG}


def get_scenario(key: str) -> Scenario | None:
    return _BY_KEY.get((key or "").strip().casefold())


@dataclass(frozen=True)
class DimensionScore:
    dimension: ScoreDimension
    score: int
    comment: str


@dataclass
class Evaluation:
    """How an attempt went.

    `scored` is false when the attempt was too short to judge. The caller shows
    that instead of numbers — a confident 72/100 derived from one exchange is a
    figure the learner will believe because it looks precise.
    """

    scored: bool = False
    scores: list[DimensionScore] = field(default_factory=list)
    summary: str = ""
    goals_met: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def overall(self) -> int | None:
        if not self.scores:
            return None
        return round(sum(s.score for s in self.scores) / len(self.scores))


def can_score(learner_turns: int, learner_characters: int) -> bool:
    return learner_turns >= MIN_LEARNER_TURNS_TO_SCORE and learner_characters >= MIN_LEARNER_CHARACTERS_TO_SCORE


def validate_evaluation(raw: dict, scenario: Scenario) -> Evaluation:
    """Clean a model's judgement into something showable.

    Scores are clamped rather than trusted, and a dimension the model omitted
    is *absent* rather than zero: zero is a claim that the learner did badly,
    and we would be making it on the model's silence.
    """
    if not isinstance(raw, dict):
        raise ValueError("The evaluation could not be read")

    scores: list[DimensionScore] = []
    reported = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    for dimension in ScoreDimension:
        entry = reported.get(dimension.value)
        value = _clamped(entry.get("score") if isinstance(entry, dict) else entry)
        if value is None:
            continue
        comment = ""
        if isinstance(entry, dict) and isinstance(entry.get("comment"), str):
            comment = " ".join(entry["comment"].split())[:300]
        scores.append(DimensionScore(dimension=dimension, score=value, comment=comment))

    if not scores:
        raise ValueError("The evaluation contained no usable scores")

    # Only goals this scenario actually has. A model listing a goal nobody set
    # would show the learner a task they were never asked to do.
    claimed = raw.get("goals_met") if isinstance(raw.get("goals_met"), list) else []
    goals_met = [
        goal
        for goal in scenario.goals
        if any(isinstance(c, str) and c.strip().casefold() == goal.casefold() for c in claimed)
    ]

    summary = ""
    if isinstance(raw.get("summary"), str):
        summary = " ".join(raw["summary"].split())[:600]

    return Evaluation(scored=True, scores=scores, summary=summary, goals_met=goals_met)


def unscored(reason: str) -> Evaluation:
    return Evaluation(scored=False, detail=reason)


def _clamped(value) -> int | None:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(MIN_SCORE, min(number, MAX_SCORE))
