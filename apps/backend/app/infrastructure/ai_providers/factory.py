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
from app.infrastructure.ai_providers.google import GeminiProvider, VertexAIProvider
from app.infrastructure.ai_providers.ollama import OllamaProvider
from app.infrastructure.ai_providers.openai_provider import OpenAIProvider

SUPPORTED_AI_PROVIDERS = ("none", "ollama", "gemini", "vertex", "openai")


def build_ai_provider(settings: Settings) -> AIProvider | None:
    """Build the configured AIProvider, or None when AI is switched off.

    Returning None rather than a null-object provider keeps "no AI
    configured" a state the caller can see and report honestly, instead of
    something indistinguishable from a provider that always fails.

    Every branch below constructs its SDK client eagerly rather than
    lazily on first use: none of `httpx.AsyncClient`, `genai.Client`, or (once
    added) `AsyncOpenAI` open a network connection at construction time —
    they only hold configuration — so doing it here costs nothing and means
    a cloud provider missing its one required field fails *now*, at the same
    "fail at startup, not at generation" point `Settings._known_ai_provider`
    already uses for an unknown provider name (issue #211's own precedent
    for this codebase's general posture on AI configuration errors).
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
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError(
                "AI_PROVIDER=gemini requires GEMINI_API_KEY to be set — get one at "
                "https://aistudio.google.com/apikey"
            )
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            max_output_tokens=settings.ai_max_output_tokens,
            context_max_chars=settings.ai_context_max_chars,
        )
    if provider == "vertex":
        if not settings.vertex_project_id:
            raise ValueError(
                "AI_PROVIDER=vertex requires VERTEX_PROJECT_ID to be set — the GCP "
                "project the Vertex AI API is enabled on"
            )
        return VertexAIProvider(
            project_id=settings.vertex_project_id,
            location=settings.vertex_location,
            model=settings.vertex_model,
            max_output_tokens=settings.ai_max_output_tokens,
            context_max_chars=settings.ai_context_max_chars,
        )
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "AI_PROVIDER=openai requires OPENAI_API_KEY to be set — get one at "
                "https://platform.openai.com/api-keys"
            )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            max_output_tokens=settings.ai_max_output_tokens,
            context_max_chars=settings.ai_context_max_chars,
        )
    raise ValueError(
        f"Unknown AI_PROVIDER '{settings.ai_provider}' — supported values are: "
        f"{', '.join(SUPPORTED_AI_PROVIDERS)}"
    )
