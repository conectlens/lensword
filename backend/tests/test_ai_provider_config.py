"""Tests for AI provider configuration and the build_ai_provider factory
(ROADMAP.md Phase 1.1 / issue #22).

The defaults must leave an existing deployment untouched: no AI settings in
the environment means no provider is built and nothing about startup
changes.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import _ai_provider, get_ai_provider
from app.config import Settings, get_settings
from app.infrastructure.ai import OllamaProvider, build_ai_provider

_AI_ENV_VARS = ("AI_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL")


@pytest.fixture()
def unset_env(monkeypatch):
    """A pristine environment — a developer's own local .env or exported
    OLLAMA_* variables must not decide whether this test passes."""
    for name in _AI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_ai_settings_default_to_a_disabled_provider(unset_env):
    settings = _settings()

    assert settings.ai_provider == "none"
    assert settings.ollama_model == "llama3.2"
    assert settings.ollama_base_url == "http://localhost:11434"


def test_build_ai_provider_returns_none_when_disabled(unset_env):
    assert build_ai_provider(_settings()) is None


def test_build_ai_provider_returns_ollama_provider_when_configured(unset_env):
    provider = build_ai_provider(_settings(ai_provider="ollama"))

    assert isinstance(provider, OllamaProvider)


def test_build_ai_provider_passes_configured_model_and_base_url(unset_env):
    provider = build_ai_provider(
        _settings(ai_provider="ollama", ollama_model="mistral", ollama_base_url="http://ollama.internal:9999")
    )

    assert provider is not None
    assert provider._model == "mistral"
    assert str(provider._client.base_url) == "http://ollama.internal:9999"


def test_settings_reject_an_unknown_provider_name_up_front(unset_env):
    """A typo in AI_PROVIDER must stop the app from starting, not lie dormant
    until the first suggestion request turns it into a 500."""
    with pytest.raises(PydanticValidationError, match="ollama"):
        _settings(ai_provider="bogus")


def test_settings_accept_the_supported_values_in_any_casing(unset_env):
    assert _settings(ai_provider="OLLAMA").ai_provider == "ollama"
    assert _settings(ai_provider=" none ").ai_provider == "none"


def _enable_ollama(monkeypatch, model="mistral", base_url="http://ollama.internal:9999"):
    """Configure AI the way an operator would — environment only — and drop
    the process-wide caches so the app rebuilds from it."""
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", model)
    monkeypatch.setenv("OLLAMA_BASE_URL", base_url)
    get_settings.cache_clear()
    _ai_provider.cache_clear()


def test_the_app_dependency_builds_the_provider_the_settings_ask_for(monkeypatch):
    """Covers the one line that connects Settings to the running app.

    Every other AI-enabled test injects a provider through
    dependency_overrides, so without this the whole feature could be dead in
    production — get_ai_provider returning None for everyone — with a fully
    green suite.
    """
    _enable_ollama(monkeypatch)

    provider = get_ai_provider()

    assert isinstance(provider, OllamaProvider)
    assert provider._model == "mistral"
    assert str(provider._client.base_url) == "http://ollama.internal:9999"


def test_the_app_dependency_yields_no_provider_when_ai_is_off(monkeypatch):
    """The other half of the same wiring: the default really does disable."""
    get_settings.cache_clear()
    _ai_provider.cache_clear()

    assert get_ai_provider() is None


def test_the_built_provider_is_reused_rather_than_rebuilt_per_request(monkeypatch):
    """The adapter owns a pooled httpx client; rebuilding it per request
    would discard the connection pool every time."""
    _enable_ollama(monkeypatch)

    assert get_ai_provider() is get_ai_provider()


def test_build_ai_provider_rejects_an_unknown_provider_name():
    """Defence in depth: settings validation is the first line, but the
    factory must not fall through to None for a value it does not know.
    model_construct skips validation so the factory's own guard is reached."""
    with pytest.raises(ValueError, match="gpt5000"):
        build_ai_provider(Settings.model_construct(ai_provider="gpt5000"))


def test_build_ai_provider_error_lists_the_supported_values():
    """An operator who typos AI_PROVIDER should be told what is valid, not
    just that their value was wrong."""
    with pytest.raises(ValueError, match="ollama"):
        build_ai_provider(Settings.model_construct(ai_provider="olama"))
