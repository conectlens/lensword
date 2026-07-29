"""Concrete MCP handlers that delegate to application use cases only."""
from typing import Any

from app.api.mappers import word_to_response
from app.application.use_cases.vocabulary import AddWordUseCase, WordInput
from app.application.use_cases.review import GetWeeklyProgressUseCase, StartReviewSessionUseCase, SubmitAnswerUseCase
from app.application.use_cases.practice import GenerateExerciseUseCase
from app.application.use_cases.extract import ExtractVocabularyUseCase
from app.application.use_cases.vocabulary import _require_word_owner
from app.domain.repositories import GroupRepository, PracticeExerciseRepository, WordRepository
from app.domain.repositories import ReviewSessionRepository
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
