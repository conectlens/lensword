"""Application use cases behind issue #188's learner-aware MCP tools.

Read-mostly by construction (issue #188 TODO 3's "an agent cannot mark a
word mastered or create a diagnosis directly"): four of the five use cases
here only read state a learner already owns. `RecordContextOccurrenceUseCase`
is the sole write, and what it writes is a single low-trust
`LearningObservation` with `context_source` set — never a `Word`/
`ReviewState` mutation (no `apply_review`/scheduler call) and never a
`Diagnosis` directly. `diagnosis_engine.py`'s `ContextLockRule` already
reads `context_source` as evidence a *future* diagnosis run may cite; this
module is the write path that field was always waiting for (see
`LearningObservation.context_source`'s docstring in diagnosis_contracts.py).

None of the response shapes here include a word's `mnemonic` or any other
private field — see `app/application/mcp/bindings.py`'s module docstring
for why that specific leak matters for this issue.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.application.mcp.contracts import CONTEXT_KINDS
from app.application.use_cases.vocabulary import _require_group_owner, _require_word_owner
from app.domain.exceptions import ValidationError
from app.domain.repositories import (
    DiagnosisRepository,
    GroupRepository,
    LearningObservationRepository,
    WordRepository,
)
from app.domain.services.cefr_progress import MASTERY_STRENGTH
from app.domain.services.diagnosis_contracts import LearningObservation
from app.domain.value_objects import ReviewOutcome, SessionMode, utcnow


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    """Account-scoped aggregate counts only — never a single word's text.

    `known_word_count` is a subset of `active_word_count`: "known" means
    mastered (matches `cefr_progress.py`'s own `MASTERY_STRENGTH` threshold,
    so this tool cannot silently disagree with the progress screen already
    shown in the app), "active" means merely started (repetitions > 0).
    """

    target_languages: tuple[str, ...]
    known_word_count: int
    active_word_count: int
    total_word_count: int
    group_count: int


class GetLanguageProfileUseCase:
    def __init__(self, group_repo: GroupRepository, word_repo: WordRepository):
        self.group_repo = group_repo
        self.word_repo = word_repo

    def execute(self, user_id: int) -> LanguageProfile:
        groups = self.group_repo.list_by_owner(user_id)
        words = [word for group in groups for word in self.word_repo.list_by_group(group.id or 0)]
        known = sum(
            1
            for word in words
            if word.review_state.repetitions > 0 and word.review_state.strength >= MASTERY_STRENGTH
        )
        active = sum(1 for word in words if word.review_state.repetitions > 0)
        languages = tuple(sorted({group.target_language.value for group in groups}))
        return LanguageProfile(
            target_languages=languages,
            known_word_count=known,
            active_word_count=active,
            total_word_count=len(words),
            group_count=len(groups),
        )


@dataclass(frozen=True, slots=True)
class KnownTermMatch:
    word_id: int
    target_language: str
    cefr_level: str | None
    known: bool
    active: bool


@dataclass(frozen=True, slots=True)
class KnownTermCheck:
    term: str
    known: bool
    active: bool
    matches: tuple[KnownTermMatch, ...]


class CheckKnownTermUseCase:
    """Exact, case-insensitive term lookup scoped to the caller's own words.

    Deliberately excludes `translations`/`definition`/`mnemonic` from the
    match shape — a caller asking "do I already know this word" only needs
    a yes/no and enough to disambiguate duplicates, not the card's content.
    """

    MAX_MATCHES = 5

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, user_id: int, term: str) -> KnownTermCheck:
        needle = term.strip().casefold()
        matches: list[KnownTermMatch] = []
        known = active = False
        for group in self.group_repo.list_by_owner(user_id):
            for word in self.word_repo.list_by_group(group.id or 0):
                if word.term.strip().casefold() != needle:
                    continue
                is_known = word.review_state.repetitions > 0 and word.review_state.strength >= MASTERY_STRENGTH
                is_active = word.review_state.repetitions > 0
                known = known or is_known
                active = active or is_active
                if len(matches) < self.MAX_MATCHES:
                    matches.append(
                        KnownTermMatch(
                            word_id=word.id or 0,
                            target_language=word.target_language.value,
                            cefr_level=word.cefr_level,
                            known=is_known,
                            active=is_active,
                        )
                    )
        return KnownTermCheck(term=term.strip(), known=known, active=active, matches=tuple(matches))


@dataclass(frozen=True, slots=True)
class WordExplanation:
    word_id: int
    term: str
    target_language: str
    cefr_level: str | None
    has_diagnosis: bool
    diagnosis_outcome: str | None
    diagnosis_confidence: float | None
    sample_size: int
    explanation: str


class ExplainWordForUserUseCase:
    """Deterministic, template-built explanation of one owned word.

    Never an AI call: this always works offline and never states a cause
    `diagnosis_engine.py` itself abstained from. If issue #187's coach
    endpoint lands, it is a strictly optional richer alternative a client
    may call instead — this tool is the one that always works.
    """

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository, diagnosis_repo: DiagnosisRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.diagnosis_repo = diagnosis_repo

    def execute(self, user_id: int, word_id: int) -> WordExplanation:
        word = _require_word_owner(self.word_repo, self.group_repo, word_id, user_id)
        diagnosis = self.diagnosis_repo.latest_for_word(user_id, word_id)
        if diagnosis is None:
            explanation = (
                f"No diagnosis has been recorded yet for '{word.term}'. "
                "Review it a few more times to build evidence."
            )
            return WordExplanation(
                word_id=word.id or 0, term=word.term, target_language=word.target_language.value,
                cefr_level=word.cefr_level, has_diagnosis=False, diagnosis_outcome=None,
                diagnosis_confidence=None, sample_size=0, explanation=explanation,
            )
        if diagnosis.is_abstention:
            explanation = (
                f"There is not yet enough evidence to explain why '{word.term}' is hard "
                f"({diagnosis.outcome}, {diagnosis.sample_size} observation(s))."
            )
        else:
            explanation = (
                f"'{word.term}' is currently diagnosed as {diagnosis.outcome} "
                f"from {diagnosis.sample_size} observation(s)."
            )
        return WordExplanation(
            word_id=word.id or 0, term=word.term, target_language=word.target_language.value,
            cefr_level=word.cefr_level, has_diagnosis=True, diagnosis_outcome=diagnosis.outcome,
            diagnosis_confidence=diagnosis.confidence, sample_size=diagnosis.sample_size, explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class StretchSuggestion:
    word_id: int
    term: str
    target_language: str
    cefr_level: str | None
    reason: str


class SuggestStretchVocabularyUseCase:
    """Bounded, deterministic "what to study next" suggestions.

    Every suggestion is a word the learner already added — this never
    invents vocabulary and never touches a Word or creates a Diagnosis
    (issue #188 TODO 3's read-mostly boundary). Ordered by repetitions then
    id, ascending, so the least-started words surface first and ties break
    the same way on every call.
    """

    DEFAULT_LIMIT = 10

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, user_id: int, group_id: int | None, limit: int | None) -> tuple[StretchSuggestion, ...]:
        bounded_limit = min(limit or self.DEFAULT_LIMIT, 50)
        if group_id is not None:
            groups = [_require_group_owner(self.group_repo, group_id, user_id)]
        else:
            groups = self.group_repo.list_by_owner(user_id)

        candidates: list[tuple] = []
        for group in groups:
            for word in self.word_repo.list_by_group(group.id or 0):
                if word.review_state.repetitions > 0 and word.review_state.strength >= MASTERY_STRENGTH:
                    continue
                reason = "not yet started" if word.review_state.repetitions == 0 else "in progress, not yet mastered"
                candidates.append((word.review_state.repetitions, word.id or 0, word, reason))
        candidates.sort(key=lambda row: (row[0], row[1]))
        return tuple(
            StretchSuggestion(
                word_id=word.id or 0, term=word.term, target_language=word.target_language.value,
                cefr_level=word.cefr_level, reason=reason,
            )
            for _, _, word, reason in candidates[:bounded_limit]
        )


@dataclass(frozen=True, slots=True)
class ContextOccurrenceInput:
    word_id: int
    context_kind: str
    outcome: str
    confirmed: bool
    operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContextOccurrenceResult:
    observation_id: str
    word_id: int
    context_source: str
    outcome: str
    recorded_at: datetime


_CONTEXT_OUTCOMES = ("correct", "incorrect")


class RecordContextOccurrenceUseCase:
    """Records one context sighting as a distinct, low-trust fact.

    This is the write path issue #229's `ContextLockRule` was left waiting
    for (see that rule's docstring in `diagnosis_engine.py`): it appends a
    `LearningObservation` whose `context_source` names where the sighting
    came from, so a *later* diagnosis run may cite it as evidence. It never
    calls `Word.apply_review`/the scheduler and never runs
    `RunDiagnosisForWordUseCase` itself — a context sighting is not a
    review answer and does not immediately move any mastery-affecting
    state, matching issue #188 TODO 3's "read-mostly" tool boundary and
    TODO 4's "distinct evidence kind, not automatically flashcard-equivalent
    mastery."

    `confirmed` must be explicitly true: the caller (CLI/host) is expected
    to have already shown the learner what is about to be recorded and
    gotten their consent, the same preview-then-confirm shape
    `context_import.py` already uses for the read side of this workflow.
    """

    def __init__(
        self,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        observation_repo: LearningObservationRepository,
    ):
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.observation_repo = observation_repo

    def execute(self, user_id: int, data: ContextOccurrenceInput) -> ContextOccurrenceResult:
        if not data.confirmed:
            raise ValidationError("record_context_occurrence requires explicit confirmation")
        if data.context_kind not in CONTEXT_KINDS:
            raise ValidationError(f"unsupported context_kind '{data.context_kind}'")
        if data.outcome not in _CONTEXT_OUTCOMES:
            raise ValidationError(f"unsupported outcome '{data.outcome}'")

        word = _require_word_owner(self.word_repo, self.group_repo, data.word_id, user_id)

        if data.operation_id is not None:
            existing = self.observation_repo.find_by_operation(user_id, data.operation_id)
            if existing is not None:
                return ContextOccurrenceResult(
                    observation_id=existing.observation_id, word_id=existing.word_id,
                    context_source=existing.context_source or "", outcome=existing.outcome.value,
                    recorded_at=existing.observed_at,
                )

        observation = LearningObservation(
            observation_id=uuid.uuid4().hex,
            word_id=word.id or 0,
            user_id=user_id,
            outcome=ReviewOutcome(data.outcome),
            session_mode=SessionMode.STANDARD,
            observed_at=utcnow(),
            operation_id=data.operation_id,
            context_source=f"context:{data.context_kind}",
        )
        saved = self.observation_repo.add(observation)
        return ContextOccurrenceResult(
            observation_id=saved.observation_id, word_id=saved.word_id,
            context_source=saved.context_source or "", outcome=saved.outcome.value,
            recorded_at=saved.observed_at,
        )
