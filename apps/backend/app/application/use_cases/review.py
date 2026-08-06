import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.entities import MnemonicNote, ReviewSession, User, Word
from app.domain.exceptions import (
    AIProviderNotConfiguredError,
    EntityNotFoundError,
    NoWordsDueError,
    PermissionDeniedError,
    ValidationError,
)
from app.application.use_cases.diagnosis import RunDiagnosisForWordUseCase
from app.application.use_cases.knowledge_graph import RecomputeKnowledgeEdgesForWordUseCase
from app.application.use_cases.vocabulary import _require_word_owner
from app.domain.repositories import (
    GroupRepository,
    MnemonicRepository,
    ReviewSessionRepository,
    UserRepository,
    WordRepository,
)
from app.domain.services.ai_provider import AIProvider
from app.domain.services.diagnosis_contracts import LearningObservation
from app.domain.services.spaced_repetition import Scheduler
from app.domain.services.mistake_memory import (
    RecordedMistake,
    build_memories,
    select_for_session,
)
from app.domain.services.weakness import categorise
from app.domain.value_objects import ReviewOutcome, SessionMode, utcnow


class StartReviewSessionUseCase:
    def __init__(
        self,
        session_repo: ReviewSessionRepository,
        word_repo: WordRepository,
        mistake_repo=None,
    ):
        self.session_repo = session_repo
        self.word_repo = word_repo
        # Only the mistakes mode needs it, so it stays optional and every other
        # caller is unaffected.
        self.mistake_repo = mistake_repo

    def execute(self, user_id: int, mode: SessionMode, group_id: int | None, limit: int = 20) -> tuple[ReviewSession, list[Word]]:
        if mode == SessionMode.MISTAKES:
            words = self._words_with_outstanding_mistakes(user_id, group_id, limit)
        else:
            words = self.word_repo.list_due_for_user(user_id, limit=limit, group_id=group_id)
        if not words:
            raise NoWordsDueError()
        session = ReviewSession(id=None, user_id=user_id, mode=mode)
        session = self.session_repo.add(session)
        return session, words

    def _words_with_outstanding_mistakes(
        self, user_id: int, group_id: int | None, limit: int
    ) -> list[Word]:
        """Words got wrong and not yet relearned, worst first.

        Deliberately ignores the due date. A mistake is worth revisiting
        whether or not the scheduler has come round to it — waiting for a word
        you already know you got wrong is the opposite of what this session is
        for.
        """
        if self.mistake_repo is None:
            return []

        rows = self.mistake_repo.list_for_user(user_id)
        if not rows:
            return []

        mistakes = [
            RecordedMistake(
                word_id=row.word_id,
                occurred_at=row.occurred_at,
                category=row.category,
                occurrences=row.occurrence_count,
            )
            for row in rows
        ]
        corrections = self.session_repo.correct_answer_times(
            user_id, sorted({m.word_id for m in mistakes})
        )
        # Over-selected, then filtered by group below: a learner studying one
        # group should not get a shorter session because their worst mistakes
        # happen to be in another.
        candidates = select_for_session(build_memories(mistakes, corrections), limit=limit * 4)

        words = []
        for word_id in candidates:
            word = self.word_repo.get_by_id(word_id)
            # A deleted word leaves its mistakes behind only briefly, but a
            # session must never fail because history outlived vocabulary.
            if word is None:
                continue
            if group_id is not None and word.group_id != group_id:
                continue
            words.append(word)
            if len(words) >= limit:
                break
        return words


@dataclass(frozen=True, slots=True)
class AnswerResult:
    word: Word
    was_new_word: bool


@dataclass(frozen=True, slots=True)
class ObservationInput:
    """Optional richer telemetry for one answer (#182, ADR 0007).

    `None` (the default in `execute`) for every caller that predates this —
    a legacy client's answer still schedules and records a mistake exactly
    as before; it just produces no `LearningObservation`, the same "no new
    branch taken" guarantee ADR 0007 states for the feature disabled.
    """

    operation_id: str | None = None
    prompt_direction: str | None = None
    hint_used: bool = False
    answer_format: str | None = None
    modality: str | None = None
    intervention_plan_ref: str | None = None
    self_reported_confidence: float | None = None


class SubmitAnswerUseCase:
    def __init__(
        self,
        session_repo: ReviewSessionRepository,
        word_repo: WordRepository,
        scheduler: Scheduler,
        mistake_repo=None,
        observation_repo=None,
        edge_repo=None,
        diagnosis_repo=None,
        acquisition_repo=None,
    ):
        self.session_repo = session_repo
        self.word_repo = word_repo
        self.scheduler = scheduler
        # Optional so every existing caller — and every test that only cares
        # about scheduling — keeps working. Recording a mistake is bookkeeping
        # beside the review, not part of it.
        self.mistake_repo = mistake_repo
        # Optional and, unlike mistake_repo, deliberately not wired by
        # default even where a caller could: the router only passes this
        # when `learning_diagnosis_enabled` is true for the account, so a
        # disabled account's request path never reaches this table at all.
        self.observation_repo = observation_repo
        # Optional so mistake recording works unchanged when nobody cares
        # about the graph consequence — a CONFUSED_WITH edge is derived
        # from mistakes, so a new one needs the same recompute a synonym
        # edit gets (#203 TODO 2).
        self.edge_repo = edge_repo
        # Same gate as observation_repo: the router only passes this when
        # learning_diagnosis_enabled is true, so a disabled account's
        # answer never triggers a diagnosis run at all.
        self.diagnosis_repo = diagnosis_repo
        # #184: the router only passes this when acquisition_loop_enabled
        # is true, so a diagnosis-driven ladder entry only ever happens for
        # an account that opted in — same gate, one level further out.
        self.acquisition_repo = acquisition_repo

    def execute(
        self,
        user_id: int,
        session_id: int,
        word_id: int,
        outcome: ReviewOutcome,
        response_time_ms: int | None,
        attempted_answer: str | None = None,
        observation: ObservationInput | None = None,
    ) -> AnswerResult:
        session = self.session_repo.get_by_id(session_id)
        if session is None:
            raise EntityNotFoundError("ReviewSession", session_id)
        if session.user_id != user_id:
            raise PermissionDeniedError("This review session belongs to another account")

        word = self.word_repo.get_by_id(word_id)
        if word is None:
            raise EntityNotFoundError("Word", word_id)

        was_new_word = word.review_state.repetitions == 0
        session.record_attempt(word_id, outcome, response_time_ms)
        self.session_repo.update(session)

        word.apply_review(outcome, self.scheduler)
        self.word_repo.update(word)

        self._record_mistake(user_id, word, outcome, attempted_answer)
        self._record_observation(
            user_id, session, word_id, outcome, response_time_ms, attempted_answer, observation
        )
        self._run_diagnosis(user_id, word_id)

        became_learned = was_new_word and outcome == ReviewOutcome.CORRECT
        return AnswerResult(word=word, was_new_word=became_learned)

    def _run_diagnosis(self, user_id: int, word_id: int) -> None:
        if self.diagnosis_repo is None or self.observation_repo is None or self.edge_repo is None:
            return
        RunDiagnosisForWordUseCase(
            self.word_repo, self.observation_repo, self.edge_repo, self.diagnosis_repo, self.acquisition_repo
        ).execute(user_id, word_id)

    def _record_observation(
        self,
        user_id: int,
        session: ReviewSession,
        word_id: int,
        outcome: ReviewOutcome,
        response_time_ms: int | None,
        attempted_answer: str | None,
        observation: ObservationInput | None,
    ) -> None:
        if self.observation_repo is None:
            return

        telemetry = observation or ObservationInput()
        if telemetry.operation_id is not None:
            # #182 TODO 1: a retry after a lost response must not record a
            # second observation for the same submission.
            existing = self.observation_repo.find_by_operation(user_id, telemetry.operation_id)
            if existing is not None:
                return

        self.observation_repo.add(
            LearningObservation(
                observation_id=uuid.uuid4().hex,
                word_id=word_id,
                user_id=user_id,
                outcome=outcome,
                session_mode=session.mode,
                observed_at=utcnow(),
                operation_id=telemetry.operation_id,
                attempted_answer=attempted_answer,
                response_time_ms=response_time_ms,
                prompt_direction=telemetry.prompt_direction,
                hint_used=telemetry.hint_used,
                answer_format=telemetry.answer_format,
                modality=telemetry.modality,
                intervention_plan_ref=telemetry.intervention_plan_ref,
                self_reported_confidence=telemetry.self_reported_confidence,
            )
        )

    def _record_mistake(
        self, user_id: int, word: Word, outcome: ReviewOutcome, attempted_answer: str | None
    ) -> None:
        """File an incorrect or skipped answer for the weakness profile.

        A confusion is only recorded when the attempt *is* another word this
        learner studies — resolved by an exact lookup rather than by guessing
        from similarity, so a misspelling that happens to resemble a word they
        own does not manufacture a pair out of a typo.
        """
        if self.mistake_repo is None or outcome == ReviewOutcome.CORRECT:
            return

        known_terms = None
        if attempted_answer and attempted_answer.strip():
            matched = self.word_repo.find_id_by_term(user_id, attempted_answer)
            # Answering a word with its own term is a grading disagreement, not
            # a confusion between two words.
            if matched is not None and matched != word.id:
                known_terms = {attempted_answer.strip().casefold(): matched}

        category, confused_with = categorise(
            outcome.value, attempted_answer, word.term, known_terms
        )
        self.mistake_repo.record(
            user_id=user_id,
            word_id=word.id,
            category=category.value,
            attempted_answer=attempted_answer,
            confused_with_word_id=confused_with,
            context="review",
        )
        if self.edge_repo is not None and confused_with is not None:
            # Recomputing for word.id alone is sufficient: the CONFUSED_WITH
            # edge this mistake produces touches word.id by construction, so
            # it lands in that word's replace_for_word batch regardless of
            # which side confused_with fell on.
            RecomputeKnowledgeEdgesForWordUseCase(self.word_repo, self.edge_repo, self.mistake_repo).execute(
                user_id, word.id
            )


class CompleteReviewSessionUseCase:
    def __init__(
        self, session_repo: ReviewSessionRepository, user_repo: UserRepository, word_repo: WordRepository
    ):
        self.session_repo = session_repo
        self.user_repo = user_repo
        self.word_repo = word_repo

    def execute(self, user_id: int, session_id: int, new_words_learned_count: int = 0) -> ReviewSession:
        session = self.session_repo.get_by_id(session_id)
        if session is None:
            raise EntityNotFoundError("ReviewSession", session_id)
        if session.user_id != user_id:
            raise PermissionDeniedError("This review session belongs to another account")

        session.new_words_learned_count = new_words_learned_count
        session.complete()
        session = self.session_repo.update(session)

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User", user_id)
        user.record_completed_session(session)
        self.user_repo.update(user)

        return session


class GetWeeklyProgressUseCase:
    """Powers the dashboard's 'words reviewed in the last 7 days' chart with
    real data instead of hardcoded numbers."""

    def __init__(self, session_repo: ReviewSessionRepository):
        self.session_repo = session_repo

    def execute(self, user_id: int) -> dict[str, int]:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        sessions = self.session_repo.list_recent_by_user(user_id, since)
        counts: dict[str, int] = {}
        for session in sessions:
            day_key = session.started_at.strftime("%a")
            counts[day_key] = counts.get(day_key, 0) + session.words_reviewed_count
        return counts


class AddMnemonicUseCase:
    def __init__(
        self, mnemonic_repo: MnemonicRepository, word_repo: WordRepository, group_repo: GroupRepository
    ):
        self.mnemonic_repo = mnemonic_repo
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, user_id: int, word_id: int, text: str) -> MnemonicNote:
        if not text.strip():
            raise ValidationError("Mnemonic text cannot be empty")
        _require_word_owner(self.word_repo, self.group_repo, word_id, user_id)
        note = MnemonicNote(id=None, word_id=word_id, author_id=user_id, text=text.strip())
        return self.mnemonic_repo.add(note)


class ListMnemonicsUseCase:
    def __init__(
        self, mnemonic_repo: MnemonicRepository, word_repo: WordRepository, group_repo: GroupRepository
    ):
        self.mnemonic_repo = mnemonic_repo
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int) -> list[MnemonicNote]:
        _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        return self.mnemonic_repo.list_by_word(word_id)


class SuggestMnemonicUseCase:
    """Ask the configured AI provider for a mnemonic for one word.

    The provider is optional by design: AI is off by default, so the use
    case is constructed with None and says so explicitly rather than the
    caller having to know whether wiring succeeded.
    """

    def __init__(
        self, word_repo: WordRepository, group_repo: GroupRepository, provider: AIProvider | None
    ):
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.provider = provider

    def resolve_word(self, owner_id: int, word_id: int) -> Word:
        """Authorize and load the word. Synchronous and database-bound.

        Split from generation so a caller can release its database
        connection before the slow await — the repositories return detached
        domain objects, so the returned Word stays usable afterwards.

        Ownership is resolved here, before any provider work. A generated
        mnemonic restates the word it was built from, so answering for
        someone else's id would hand back their vocabulary; and checking
        before the provider branch keeps a foreign id from being
        distinguishable by its 'disabled' answer when AI is switched off.
        """
        return _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)

    async def generate(self, word: Word) -> str:
        """The slow half. Touches no repository."""
        if self.provider is None:
            raise AIProviderNotConfiguredError()
        return await self.provider.suggest_mnemonic(word.term, self._context_for(word))

    async def execute(self, owner_id: int, word_id: int) -> str:
        """Both halves, for callers with no connection to release."""
        return await self.generate(self.resolve_word(owner_id, word_id))

    @staticmethod
    def _context_for(word: Word) -> str:
        language = word.target_language.value
        if word.translations:
            return f"a {language} word meaning {', '.join(word.translations)}"
        return f"a {language} word"


class VoteMnemonicUseCase:
    def __init__(
        self, mnemonic_repo: MnemonicRepository, word_repo: WordRepository, group_repo: GroupRepository
    ):
        self.mnemonic_repo = mnemonic_repo
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int, mnemonic_id: int, upvote: bool) -> MnemonicNote:
        _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        note = self.mnemonic_repo.get_by_id(mnemonic_id)
        if note is None:
            raise EntityNotFoundError("MnemonicNote", mnemonic_id)
        if note.word_id != word_id:
            # Ownership was checked against the word in the path, so a
            # mnemonic hanging off a different word has not been authorized
            # by that check — pairing your own word_id with someone else's
            # mnemonic_id must not slip through.
            raise EntityNotFoundError("MnemonicNote", mnemonic_id)
        note.upvote() if upvote else note.downvote()
        return self.mnemonic_repo.update(note)
