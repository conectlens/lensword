"""Concrete MCP handlers that delegate to application use cases only."""
from typing import Any

from app.api.mappers import word_to_response
from app.application.use_cases.vocabulary import AddWordUseCase, WordInput
from app.domain.repositories import GroupRepository, WordRepository
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
