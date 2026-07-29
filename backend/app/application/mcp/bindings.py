"""Concrete MCP handlers that delegate to application use cases only."""
from typing import Any

from app.api.mappers import word_to_response
from app.application.use_cases.vocabulary import AddWordUseCase, WordInput
from app.application.use_cases.review import GetWeeklyProgressUseCase
from app.domain.repositories import GroupRepository, WordRepository
from app.domain.repositories import ReviewSessionRepository
from app.domain.value_objects import SupportedLanguage


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
