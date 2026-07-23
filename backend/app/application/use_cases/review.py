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
from app.application.use_cases.vocabulary import _require_word_owner
from app.domain.repositories import (
    GroupRepository,
    MnemonicRepository,
    ReviewSessionRepository,
    UserRepository,
    WordRepository,
)
from app.domain.services.ai_provider import AIProvider
from app.domain.services.spaced_repetition import Scheduler
from app.domain.value_objects import ReviewOutcome, SessionMode


class StartReviewSessionUseCase:
    def __init__(self, session_repo: ReviewSessionRepository, word_repo: WordRepository):
        self.session_repo = session_repo
        self.word_repo = word_repo

    def execute(self, user_id: int, mode: SessionMode, group_id: int | None, limit: int = 20) -> tuple[ReviewSession, list[Word]]:
        due_words = self.word_repo.list_due_for_user(user_id, limit=limit, group_id=group_id)
        if not due_words:
            raise NoWordsDueError()
        session = ReviewSession(id=None, user_id=user_id, mode=mode)
        session = self.session_repo.add(session)
        return session, due_words


@dataclass(frozen=True, slots=True)
class AnswerResult:
    word: Word
    was_new_word: bool


class SubmitAnswerUseCase:
    def __init__(self, session_repo: ReviewSessionRepository, word_repo: WordRepository, scheduler: Scheduler):
        self.session_repo = session_repo
        self.word_repo = word_repo
        self.scheduler = scheduler

    def execute(
        self, user_id: int, session_id: int, word_id: int, outcome: ReviewOutcome, response_time_ms: int | None
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

        became_learned = was_new_word and outcome == ReviewOutcome.CORRECT
        return AnswerResult(word=word, was_new_word=became_learned)


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

    def execute(self, owner_id: int, word_id: int) -> str:
        # Ownership is resolved before anything else. A generated mnemonic
        # restates the word it was built from, so answering for someone
        # else's id would hand back their vocabulary; and checking before the
        # provider branch keeps a foreign id from being distinguishable by
        # its 'disabled' answer when AI is switched off.
        word = _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        if self.provider is None:
            raise AIProviderNotConfiguredError()
        return self.provider.suggest_mnemonic(word.term, self._context_for(word))

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
