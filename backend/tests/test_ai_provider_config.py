"""Tests for AI provider configuration and the build_ai_provider factory
(ROADMAP.md Phase 1.1 / issue #22).

The defaults must leave an existing deployment untouched: no AI settings in
the environment means no provider is built and nothing about startup
changes.
"""
from __future__ import annotations

import pytest

from app.config import Settings
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


def test_build_ai_provider_rejects_an_unknown_provider_name(unset_env):
    with pytest.raises(ValueError, match="gpt5000"):
        build_ai_provider(_settings(ai_provider="gpt5000"))


def test_build_ai_provider_error_lists_the_supported_values(unset_env):
    """An operator who typos AI_PROVIDER should be told what is valid, not
    just that their value was wrong."""
    with pytest.raises(ValueError, match="ollama"):
        build_ai_provider(_settings(ai_provider="olama"))
