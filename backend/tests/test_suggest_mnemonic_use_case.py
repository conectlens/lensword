"""Unit tests for SuggestMnemonicUseCase (ROADMAP.md Phase 1.1 / issue #22).

No HTTP and no database — the use case is exercised against stub
repositories and stub providers so that its outcomes (not owned, not found,
not configured, provider unavailable, success) are pinned down independently
of the API layer that later translates them into status codes and a status
field.
"""
from __future__ import annotations

import pytest

from app.application.use_cases.review import SuggestMnemonicUseCase
from app.domain.entities import Group, Word
from app.domain.exceptions import (
    AIProviderNotConfiguredError,
    AIProviderUnavailableError,
    EntityNotFoundError,
    PermissionDeniedError,
)
from app.domain.value_objects import SupportedLanguage

OWNER_ID = 1
STRANGER_ID = 2
GROUP_ID = 10


class _StubWordRepo:
    def __init__(self, word: Word | None):
        self._word = word

    def get_by_id(self, word_id: int) -> Word | None:
        return self._word


class _StubGroupRepo:
    def __init__(self, group: Group | None):
        self._group = group

    def get_by_id(self, group_id: int) -> Group | None:
        return self._group


class _RecordingProvider:
    def __init__(self, reply: str = "Picture a dog wearing a beret."):
        self._reply = reply
        self.calls: list[tuple[str, str]] = []

    def suggest_mnemonic(self, word: str, context: str) -> str:
        self.calls.append((word, context))
        return self._reply


class _UnavailableProvider:
    def suggest_mnemonic(self, word: str, context: str) -> str:
        raise AIProviderUnavailableError("The AI provider is not reachable")


def _word(**overrides) -> Word:
    defaults = dict(
        id=7,
        group_id=GROUP_ID,
        term="perro",
        target_language=SupportedLanguage.SPANISH,
        translations=["dog"],
    )
    defaults.update(overrides)
    return Word(**defaults)


def _group(owner_id: int = OWNER_ID) -> Group:
    return Group(id=GROUP_ID, owner_id=owner_id, name="Spanish", target_language=SupportedLanguage.SPANISH)


def _use_case(provider, word: Word | None = ..., group: Group | None = ...) -> SuggestMnemonicUseCase:
    word = _word() if word is ... else word
    group = _group() if group is ... else group
    return SuggestMnemonicUseCase(_StubWordRepo(word), _StubGroupRepo(group), provider)


def test_returns_the_providers_suggestion():
    provider = _RecordingProvider("Think of a 'purr-oh' that barks.")

    result = _use_case(provider).execute(OWNER_ID, 7)

    assert result == "Think of a 'purr-oh' that barks."


def test_refuses_a_word_owned_by_another_account():
    """The repositories' get_by_id are deliberately unscoped, so the use case
    owns the ownership check — same as every word use case in vocabulary.py."""
    provider = _RecordingProvider()
    use_case = _use_case(provider)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(STRANGER_ID, 7)

    assert provider.calls == [], "the provider must not see another account's word"


def test_ownership_is_enforced_even_when_no_provider_is_configured():
    """Otherwise the endpoint still answers 'disabled' for a foreign id and
    leaks which word ids exist."""
    use_case = _use_case(None)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(STRANGER_ID, 7)


def test_passes_the_term_and_a_context_built_from_the_word():
    provider = _RecordingProvider()

    _use_case(provider).execute(OWNER_ID, 7)

    assert len(provider.calls) == 1
    term, context = provider.calls[0]
    assert term == "perro"
    assert "Spanish" in context
    assert "dog" in context


def test_context_is_still_usable_when_the_word_has_no_translations():
    provider = _RecordingProvider()

    _use_case(provider, word=_word(translations=[])).execute(OWNER_ID, 7)

    _term, context = provider.calls[0]
    assert context.strip() != ""
    assert "Spanish" in context


def test_raises_not_configured_when_no_provider_is_wired():
    with pytest.raises(AIProviderNotConfiguredError):
        _use_case(None).execute(OWNER_ID, 7)


def test_raises_not_found_for_an_unknown_word():
    with pytest.raises(EntityNotFoundError):
        _use_case(_RecordingProvider(), word=None).execute(OWNER_ID, 999)


def test_unknown_word_is_reported_even_when_no_provider_is_configured():
    """A bad word id is a bad word id regardless of AI configuration —
    otherwise enabling Ollama would change a 404 into a 200."""
    with pytest.raises(EntityNotFoundError):
        _use_case(None, word=None).execute(OWNER_ID, 999)


def test_raises_not_found_when_the_words_group_has_vanished():
    with pytest.raises(EntityNotFoundError):
        _use_case(_RecordingProvider(), group=None).execute(OWNER_ID, 7)


def test_lets_provider_unavailability_propagate():
    with pytest.raises(AIProviderUnavailableError):
        _use_case(_UnavailableProvider()).execute(OWNER_ID, 7)


def test_not_configured_is_a_distinct_error_from_unavailable():
    """The API layer reports these as different statuses, so they must not
    collapse into one another through inheritance."""
    assert not issubclass(AIProviderNotConfiguredError, AIProviderUnavailableError)
    assert not issubclass(AIProviderUnavailableError, AIProviderNotConfiguredError)
