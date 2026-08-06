"""AIProvider port (hexagonal-architecture sense).

Decoupled from any specific backend (Ollama, a cloud LLM, etc.) — concrete
providers live in infrastructure/ and are wired up in Phase 1. Zero
third-party/framework imports here, preserving the domain layer's boundary
(see app.domain.repositories module docstring for the same rule applied to
data-access ports).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.domain.services.conversation import TutorContext, Turn
    from app.domain.services.scenarios import Scenario


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
    cefr_level: str | None = None


@dataclass(frozen=True, slots=True)
class WordEnrichment:
    term: str
    target_language: str
    translations: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    part_of_speech: str | None = None
    cefr_level: str | None = None
    pronunciation: str | None = None
    examples: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    collocations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # Deliberately the same values as `tags` (issue #202 TODO 5): the AI is
    # asked for "tags", but the knowledge graph, learning paths, and
    # scenario matching all read `Word.topics`, not `Word.tags`. Rather than
    # rename the AI's own contract, this field is populated from the same
    # parsed value so every downstream consumer can read `topics` and get
    # real data instead of an empty list. `tags` is kept for the callers
    # that already display it.
    topics: list[str] = field(default_factory=list)
    mnemonic: str | None = None
    category: str | None = None
    confidence: float | None = None
    provider: str = "unknown"
    model: str = "unknown"


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

    async def enrich_word(
        self, term: str, source_language: str | None, target_language: str
    ) -> WordEnrichment: ...

    async def translate_in_context(
        self, word: str, sentence: str, source_language: str | None, target_language: str
    ) -> WordEnrichment: ...

    async def generate_learning_path(
        self, goal: str, target_language: str, max_milestones: int, min_milestones: int
    ) -> list[dict]:
        """Propose milestones for a stated goal (#137).

        Returns raw dictionaries rather than a typed plan: the caller bounds
        and cleans them, because a model's output is a proposal and validating
        it inside the adapter would put that judgement in the one place a
        different provider would have to reimplement.

        `min_milestones` exists alongside `max_milestones` because stating
        only a ceiling ("at most N") does not stop a model reading a goal as
        a single task and returning one milestone for it (issue #212) —
        `validate_plan`'s own floor then rejects the whole plan as unusable.
        Naming the floor in the request is cheaper than discovering it was
        missing after the fact.
        """
        ...

    async def generate_field(
        self, field: str, term: str, source_language: str | None, target_language: str, context: str | None = None
    ) -> str: ...

    async def converse(self, context: "TutorContext", learner_text: str) -> dict:
        """One reply in the conversation tutor (#135).

        Returns a raw dict for the caller to validate — `{"reply": str,
        "corrections": [...]}` — the same "provider proposes, caller cleans"
        split as `generate_learning_path`.
        """
        ...

    async def evaluate_scenario(self, scenario: "Scenario", transcript: list["Turn"]) -> dict:
        """Score a finished role-play attempt (#136).

        Returns a raw dict — `{"scores": {...}, "goals_met": [...], "summary":
        str}` — for the caller to validate and clamp.
        """
        ...
