"""Adaptive companion conversation context (#194 TODO 2).

Pure, zero-I/O bounding of the facts a companion session may be told about
before it talks: the current goal, active words, due items, recent
evidence-backed confusion, and the currently-selected intervention, if any.

The separation this module exists to enforce mirrors
`app.domain.services.companion_coach`: `CoachEvidence` there is a closed,
code-generated fact, kept apart from `CoachRequest`/`CoachContent`, which
are what gets *generated*. Here, `ConversationContext` is the fact side —
each section is its own small, independently bounded tuple of frozen
dataclasses, built only from persisted domain state (never from anything a
learner or a provider wrote) and it is never itself a prompt string. Turning
these facts into a system instruction (or a coach request) is orchestration
that belongs one layer up, the same way `build_coach_request` sits above
`companion_coach.py`'s evidence dataclasses rather than inside them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Each section is capped independently, so a learner with hundreds of
# active words or a long confusion history can never crowd out the other
# sections — or push a prompt built from this context past a model's window.
MAX_ACTIVE_WORDS = 10
MAX_DUE_ITEMS = 10
MAX_CONFUSION_ITEMS = 5


@dataclass(frozen=True, slots=True)
class ActiveWordFact:
    word_id: int
    term: str
    target_language: str
    cefr_level: str | None = None


@dataclass(frozen=True, slots=True)
class DueItemFact:
    word_id: int
    term: str
    target_language: str


@dataclass(frozen=True, slots=True)
class ConfusionFact:
    """One piece of recent, evidence-backed confusion (#185's `Diagnosis`)
    — never an abstention (`Diagnosis.is_abstention`), since "we don't know
    yet" is not a confusion worth telling the companion about."""

    word_id: int
    outcome: str
    confidence: float | None
    sample_size: int


@dataclass(frozen=True, slots=True)
class SelectedInterventionFact:
    """The one currently-active `InterventionPlan` most relevant to this
    session, if any — never more than one, so a companion session has a
    single, unambiguous "what are we working on" answer rather than a list
    it has to rank itself."""

    plan_id: int | None
    word_id: int
    strategy: str
    diagnosis_outcome: str
    rationale: str


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """Everything a companion session may be told about the learner right
    now, already bounded. Facts only — never rendered prose, never an
    instruction. `app.application.use_cases.conversation_context` is the
    one place these get assembled from real repositories; anything that
    turns this into a prompt lives further up the stack still."""

    session_id: str
    goal: str | None
    active_words: tuple[ActiveWordFact, ...] = ()
    due_items: tuple[DueItemFact, ...] = ()
    confusion: tuple[ConfusionFact, ...] = ()
    selected_intervention: SelectedInterventionFact | None = None


def build_conversation_context(
    session_id: str,
    goal: str | None,
    active_words: list[ActiveWordFact],
    due_items: list[DueItemFact],
    confusion: list[ConfusionFact],
    selected_intervention: SelectedInterventionFact | None,
) -> ConversationContext:
    """Bound every section independently before it leaves the domain layer,
    the same "clean and bound before it reaches a prompt" role
    `app.domain.services.conversation.build_context` plays for the older
    conversation tutor.
    """
    return ConversationContext(
        session_id=session_id,
        goal=(goal or "").strip()[:500] or None,
        active_words=tuple(active_words[:MAX_ACTIVE_WORDS]),
        due_items=tuple(due_items[:MAX_DUE_ITEMS]),
        confusion=tuple(confusion[:MAX_CONFUSION_ITEMS]),
        selected_intervention=selected_intervention,
    )
