"""AI-backed vocabulary extraction with an explicit demo fallback."""
from __future__ import annotations

import re

from app.domain.exceptions import AIProviderNotConfiguredError, EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import GroupRepository
from app.domain.services.ai_provider import AIProvider, ExtractedVocabulary


class ExtractVocabularyUseCase:
    def __init__(
        self,
        group_repo: GroupRepository,
        provider: AIProvider | None,
        *,
        fallback_enabled: bool = False,
    ):
        self.group_repo = group_repo
        self.provider = provider
        self.fallback_enabled = fallback_enabled

    async def execute(
        self,
        owner_id: int,
        group_id: int,
        text: str,
        source_language: str | None,
        target_language: str,
        max_items: int,
        min_level: str | None = None,
    ) -> tuple[list[ExtractedVocabulary], str]:
        group = self.group_repo.get_by_id(group_id)
        if group is None:
            raise EntityNotFoundError("Group", group_id)
        if group.owner_id != owner_id:
            raise PermissionDeniedError("This group belongs to another account")

        if self.provider is not None:
            items = await self.provider.extract_vocabulary(text, source_language, target_language, max_items)
            return self._filter_level(items, min_level, max_items), "ai"
        if not self.fallback_enabled:
            raise AIProviderNotConfiguredError()
        return self._fallback(text, max_items), "fallback"

    @staticmethod
    def _filter_level(items: list[ExtractedVocabulary], min_level: str | None, max_items: int) -> list[ExtractedVocabulary]:
        if min_level is None:
            return items[:max_items]
        ranks = {level: index for index, level in enumerate(("A1", "A2", "B1", "B2", "C1", "C2"))}
        minimum = ranks[min_level]
        return [item for item in items if item.cefr_level is None or ranks.get(item.cefr_level.upper(), minimum) >= minimum][:max_items]

    @staticmethod
    def _fallback(text: str, max_items: int) -> list[ExtractedVocabulary]:
        """Tiny deterministic extractor used only when explicitly enabled.

        It is intentionally not a production replacement for the configured
        provider: candidates have no AI translations/examples and are labelled
        as fallback output at the API boundary.
        """
        candidates: list[ExtractedVocabulary] = []
        seen: set[str] = set()
        for token in re.findall(r"[^\W\d_][\w'-]*", text, flags=re.UNICODE):
            normalized = token.casefold()
            if len(normalized) < 3 or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(ExtractedVocabulary(term=token))
            if len(candidates) == max_items:
                break
        return candidates
