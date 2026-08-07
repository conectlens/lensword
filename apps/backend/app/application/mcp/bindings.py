"""Concrete MCP handlers that delegate to application use cases only."""
from typing import Any

from app.api.mappers import word_to_response
from app.application.use_cases.vocabulary import AddWordUseCase, SearchWordsUseCase, WordInput
from app.application.use_cases.review import GetWeeklyProgressUseCase, StartReviewSessionUseCase, SubmitAnswerUseCase
from app.application.use_cases.practice import GenerateExerciseUseCase
from app.application.use_cases.extract import ExtractVocabularyUseCase
from app.application.use_cases.vocabulary import _require_word_owner
from app.application.use_cases.companion_sessions import (
    FinishCompanionSessionUseCase,
    GetCompanionSessionUseCase,
    StartCompanionSessionUseCase,
    TransitionCompanionSessionUseCase,
)
from app.domain.exceptions import PermissionDeniedError, ValidationError
from app.domain.repositories import (
    CompanionSessionRepository,
    GroupRepository,
    PracticeExerciseRepository,
    RecallSettingsRepository,
    WordRepository,
)
from app.domain.repositories import ReviewSessionRepository
from app.domain.services.companion_sessions import CompanionSession
from app.domain.value_objects import SupportedLanguage
from app.domain.value_objects import ReviewOutcome, SessionMode
from app.domain.services.spaced_repetition import Scheduler
from app.domain.services.ai_provider import AIProvider


def add_word_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        word = AddWordUseCase(words, groups).execute(
            user_id,
            int(payload["group_id"]),
            WordInput(
                term=str(payload["term"]), target_language=SupportedLanguage(payload["target_language"]),
                translations=[str(value) for value in payload.get("translations", [])],
            ),
        )
        return word_to_response(word).model_dump(mode="json")
    return handle


def due_reviews_handler(words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        limit = min(int(payload.get("limit", 20)), 100)
        group_id = int(payload["group_id"]) if payload.get("group_id") is not None else None
        return {"items": [word_to_response(word).model_dump(mode="json") for word in words.list_due_for_user(user_id, limit, group_id)], "next_cursor": None}
    return handle


def search_words_handler(words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        items = SearchWordsUseCase(words, groups).execute(user_id, str(payload.get("query", "")), min(int(payload.get("limit", 20)), 100))
        return {"items": [word_to_response(word).model_dump(mode="json") for word in items], "next_cursor": None}
    return handle


def learning_progress_handler(sessions: ReviewSessionRepository):
    def handle(user_id: int, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"weekly_counts": GetWeeklyProgressUseCase(sessions).execute(user_id)}
    return handle


def generate_exercises_handler(exercises: PracticeExerciseRepository, words: WordRepository, groups: GroupRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        word = _require_word_owner(words, groups, int(payload["word_id"]), user_id)
        exercise = GenerateExerciseUseCase(exercises, words).execute(user_id, word, str(payload.get("kind", "translation")))
        return {"id": exercise.id, "word_id": exercise.word_id, "kind": exercise.kind, "prompt": exercise.prompt, "options": exercise.options}
    return handle


def create_study_session_handler(sessions, words: WordRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        session, due_words = StartReviewSessionUseCase(sessions, words).execute(user_id, SessionMode.STANDARD, payload.get("group_id"), min(int(payload.get("limit", 20)), 100))
        return {"session_id": session.id, "words": [word_to_response(word).model_dump(mode="json") for word in due_words]}
    return handle


def record_answer_handler(sessions, words: WordRepository, scheduler: Scheduler):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = SubmitAnswerUseCase(sessions, words, scheduler).execute(user_id, int(payload["session_id"]), int(payload["word_id"]), ReviewOutcome(payload["outcome"]), payload.get("response_time_ms"))
        return {"word": word_to_response(result.word).model_dump(mode="json"), "was_new_word_learned": result.was_new_word}
    return handle


def extract_vocabulary_handler(groups: GroupRepository, provider: AIProvider | None):
    async def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        items, source = await ExtractVocabularyUseCase(groups, provider).execute(user_id, int(payload["group_id"]), str(payload["text"]), payload.get("source_language"), str(payload["target_language"]), min(int(payload.get("max_items", 20)), 50), payload.get("min_level"))
        return {"source": source, "items": [{"term": item.term, "translations": item.translations, "examples": item.examples, "cefr_level": item.cefr_level} for item in items]}
    return handle


def _companion_session_to_dict(session: CompanionSession) -> dict[str, Any]:
    """The MCP tool surface's view of a session (#193 TODO 1) — the same
    fields the REST `CompanionSessionResponse` exposes (see
    app.api.routers.companion._session_response), minus the turn list: a
    tool result stays a bounded summary, and the full transcript is what the
    `lensword://session/{session_id}` resource is for."""
    return {
        "id": session.id,
        "connection_id": session.connection_id,
        "client_id": session.client_id,
        "goal": session.goal,
        "language": session.language,
        "group_id": session.group_id,
        "difficulty": session.difficulty,
        "active_activity": session.active_activity,
        "summary": session.summary,
        "status": session.status.value,
        "revision": session.revision,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _require_companion_enabled(settings: RecallSettingsRepository, user_id: int) -> None:
    """Same gate as app.api.routers.companion._require_enabled: the MCP
    tool surface must not be a back door around the per-account
    `ai_companion_enabled` flag that the REST endpoints enforce."""
    record = settings.get_by_user(user_id)
    if not record or not record.ai_companion_enabled:
        raise PermissionDeniedError("AI Companion is not enabled")


def start_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session = StartCompanionSessionUseCase(sessions).execute(
            user_id,
            connection_id=str(payload["connection_id"]),
            client_id=str(payload["client_id"]),
            goal=payload.get("goal"),
            language=payload.get("language"),
            group_id=int(payload["group_id"]) if payload.get("group_id") is not None else None,
            difficulty=payload.get("difficulty"),
            active_activity=payload.get("active_activity"),
        )
        return _companion_session_to_dict(session)
    return handle


def get_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        session = GetCompanionSessionUseCase(sessions).execute(user_id, str(payload["session_id"]))
        return _companion_session_to_dict(session)
    return handle


def _companion_transition_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository, action: str):
    def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        try:
            session = TransitionCompanionSessionUseCase(sessions).execute(
                user_id, str(payload["session_id"]), lambda s: getattr(s, action)()
            )
        except ValueError as exc:
            # An invalid transition (e.g. resuming a revoked session) is a
            # plain ValueError from the domain object, not a DomainError —
            # the REST router catches it itself, but nothing upstream of an
            # MCP handler does, and an uncaught ValueError here would surface
            # as an opaque 500 instead of the clean 400 every other MCP
            # validation failure gets from main.py's DomainError handler.
            raise ValidationError(str(exc)) from exc
        return _companion_session_to_dict(session)
    return handle


def resume_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    return _companion_transition_handler(sessions, settings, "resume")


def pause_companion_session_handler(sessions: CompanionSessionRepository, settings: RecallSettingsRepository):
    return _companion_transition_handler(sessions, settings, "pause")


def finish_companion_session_handler(
    sessions: CompanionSessionRepository, settings: RecallSettingsRepository, provider: AIProvider | None
):
    async def handle(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_companion_enabled(settings, user_id)
        try:
            session = await FinishCompanionSessionUseCase(sessions, provider).execute(user_id, str(payload["session_id"]))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return _companion_session_to_dict(session)
    return handle
