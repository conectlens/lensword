"""The settings-driven factory that picks (and builds) one AIProvider.

Kept as its own module so nothing else in this package needs to import every
concrete provider just to build one — `build_ai_provider` is the one place
that reads `Settings` and does that.

SUPPORTED_AI_PROVIDERS duplicates the tuple of the same name in
`app/config.py` (used by `Settings._known_ai_provider`) rather than being
imported from it. That is deliberate, not an oversight: `app/config.py`
cannot import from this package without a circular import (this module
already imports `from app.config import Settings` for the factory's
signature), so the two tuples are kept in sync by hand. Adding a provider
here means updating both.
"""
from __future__ import annotations

from app.config import Settings
from app.domain.services.ai_provider import AIProvider
from app.infrastructure.ai_providers.ollama import OllamaProvider

# TODO(#315, in progress): "gemini", "vertex", "openai" are added here once
# their adapters (google.py, openai_provider.py) exist.
SUPPORTED_AI_PROVIDERS = ("none", "ollama")


def build_ai_provider(settings: Settings) -> AIProvider | None:
    """Build the configured AIProvider, or None when AI is switched off.

    Returning None rather than a null-object provider keeps "no AI
    configured" a state the caller can see and report honestly, instead of
    something indistinguishable from a provider that always fails.
    """
    provider = settings.ai_provider.strip().lower()
    if provider == "none":
        return None
    if provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            max_output_tokens=settings.ai_max_output_tokens,
            context_max_chars=settings.ai_context_max_chars,
        )
    raise ValueError(
        f"Unknown AI_PROVIDER '{settings.ai_provider}' — supported values are: "
        f"{', '.join(SUPPORTED_AI_PROVIDERS)}"
    )
