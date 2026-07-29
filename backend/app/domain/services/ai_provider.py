"""AIProvider port (hexagonal-architecture sense).

Decoupled from any specific backend (Ollama, a cloud LLM, etc.) — concrete
providers live in infrastructure/ and are wired up in Phase 1. Zero
third-party/framework imports here, preserving the domain layer's boundary
(see app.domain.repositories module docstring for the same rule applied to
data-access ports).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExtractedVocabulary:
    """A bounded vocabulary candidate returned by an AI provider.

    This transport-neutral record deliberately contains only the fields the
    Phase 0 extraction API can prove. Rich enrichment belongs to the next
    phase rather than being represented by loosely typed provider dictionaries.
    """

    term: str
    translations: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    """Awaitable by design.

    Generation takes seconds, so a synchronous port would force every caller
    to hold an OS thread for the duration; under load that exhausts the
    server's bounded threadpool and stalls unrelated requests. `async def` in
    a Protocol is plain language syntax and imports nothing, so the domain
    layer stays framework-free.
    """

    async def suggest_mnemonic(self, word: str, context: str) -> str: ...

    async def extract_vocabulary(
        self, text: str, source_language: str | None, target_language: str, max_items: int
    ) -> list[ExtractedVocabulary]: ...
