"""Unit tests for SuggestMnemonicUseCase (ROADMAP.md Phase 1.1 / issue #22).

No HTTP and no database — the use case is exercised against a stub word
repository and stub providers so that its three outcomes (not configured,
provider unavailable, success) are pinned down independently of the API
layer that later translates them into a status field.
"""
from __future__ import annotations

import pytest

from app.application.use_cases.review import SuggestMnemonicUseCase
from app.domain.entities import Word
from app.domain.exceptions import (
    AIProviderNotConfiguredError,
    AIProviderUnavailableError,
    EntityNotFoundError,
)
from app.domain.value_objects import SupportedLanguage


class _StubWordRepo:
    def __init__(self, word: Word | None):
        self._word = word

    def get_by_id(self, word_id: int) -> Word | None:
        return self._word


class _RecordingProvider:
    def __init__(self, reply: str = "Picture a dog wearing a beret."):
        self._reply = reply
        self.calls: list[tuple[str, str]] = []

    def suggest_mnemonic(self, word: str, context: str) -> str:
        self.calls.append((word, context))
        return self._reply


class _UnavailableProvider:
    def suggest_mnemonic(self, word: str, context: str) -> str:
        raise AIProviderUnavailableError("Ollama is not reachable at http://localhost:11434")


def _word(**overrides) -> Word:
    defaults = dict(
        id=7,
        group_id=1,
        term="perro",
        target_language=SupportedLanguage.SPANISH,
        translations=["dog"],
    )
    defaults.update(overrides)
    return Word(**defaults)


def test_returns_the_providers_suggestion():
    provider = _RecordingProvider("Think of a 'purr-oh' that barks.")

    result = SuggestMnemonicUseCase(_StubWordRepo(_word()), provider).execute(7)

    assert result == "Think of a 'purr-oh' that barks."


def test_passes_the_term_and_a_context_built_from_the_word():
    provider = _RecordingProvider()

    SuggestMnemonicUseCase(_StubWordRepo(_word()), provider).execute(7)

    assert len(provider.calls) == 1
    term, context = provider.calls[0]
    assert term == "perro"
    assert "Spanish" in context
    assert "dog" in context


def test_context_is_still_usable_when_the_word_has_no_translations():
    provider = _RecordingProvider()

    SuggestMnemonicUseCase(_StubWordRepo(_word(translations=[])), provider).execute(7)

    _term, context = provider.calls[0]
    assert context.strip() != ""
    assert "Spanish" in context


def test_raises_not_configured_when_no_provider_is_wired():
    use_case = SuggestMnemonicUseCase(_StubWordRepo(_word()), None)

    with pytest.raises(AIProviderNotConfiguredError):
        use_case.execute(7)


def test_raises_not_found_for_an_unknown_word():
    use_case = SuggestMnemonicUseCase(_StubWordRepo(None), _RecordingProvider())

    with pytest.raises(EntityNotFoundError):
        use_case.execute(999)


def test_unknown_word_is_reported_even_when_no_provider_is_configured():
    """A bad word id is a bad word id regardless of AI configuration —
    otherwise enabling Ollama would change a 404 into a 200."""
    use_case = SuggestMnemonicUseCase(_StubWordRepo(None), None)

    with pytest.raises(EntityNotFoundError):
        use_case.execute(999)


def test_lets_provider_unavailability_propagate():
    use_case = SuggestMnemonicUseCase(_StubWordRepo(_word()), _UnavailableProvider())

    with pytest.raises(AIProviderUnavailableError):
        use_case.execute(7)


def test_not_configured_is_a_distinct_error_from_unavailable():
    """The API layer reports these as different statuses, so they must not
    collapse into one another through inheritance."""
    assert not issubclass(AIProviderNotConfiguredError, AIProviderUnavailableError)
    assert not issubclass(AIProviderUnavailableError, AIProviderNotConfiguredError)
