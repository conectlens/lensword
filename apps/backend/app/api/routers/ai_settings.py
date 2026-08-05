"""Admin-only effective AI provider configuration."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentAdmin, _ai_provider
from app.api.schemas.ai_settings import (
    AISettingsResponse,
    AISettingsUpdateRequest,
    OllamaProbeResponse,
)
from app.config import AISettingsUpdate, get_effective_ai_settings, save_effective_ai_settings
from app.api.routers.ai import clear_ai_response_cache
from app.infrastructure.ollama_probe import probe_ollama

router = APIRouter(prefix="/api/v1/ai-settings", tags=["AI settings"])


def _response(settings) -> AISettingsResponse:
    return AISettingsResponse(
        provider=settings.ai_provider,
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        max_output_tokens=settings.ai_max_output_tokens,
        context_max_chars=settings.ai_context_max_chars,
    )


@router.get("", response_model=AISettingsResponse)
def get_ai_settings(_admin: CurrentAdmin) -> AISettingsResponse:
    return _response(get_effective_ai_settings())


@router.put("", response_model=AISettingsResponse)
def update_ai_settings(payload: AISettingsUpdateRequest, _admin: CurrentAdmin) -> AISettingsResponse:
    try:
        settings = save_effective_ai_settings(
            AISettingsUpdate(
                ai_provider=payload.provider,
                ollama_model=payload.model,
                ollama_base_url=str(payload.base_url).rstrip("/"),
                ai_max_output_tokens=payload.max_output_tokens,
                ai_context_max_chars=payload.context_max_chars,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    # The dependency caches the provider so every subsequent request must be
    # rebuilt from the configuration just persisted above.
    _ai_provider.cache_clear()
    # Cached responses are keyed by provider and model, so a change already
    # makes the old entries unreachable rather than wrong. Dropped anyway so
    # they do not sit in memory for the rest of the TTL describing a
    # configuration that no longer exists.
    clear_ai_response_cache()
    return _response(settings)


@router.get("/probe", response_model=OllamaProbeResponse)
def probe(_admin: CurrentAdmin) -> OllamaProbeResponse:
    """Check whether Ollama is reachable and has a usable model.

    Admin-only, like the rest of this router. The response names the
    deployment's base URL and every model installed on that host, which is
    infrastructure detail rather than something a learner needs.

    The three failure modes are reported separately — nothing listening, not
    Ollama, running but no usable model — because a single "AI unavailable"
    would leave someone with Ollama running and no model pulled with no idea
    what to do next.
    """
    settings = get_effective_ai_settings()
    status_ = probe_ollama(settings.ollama_base_url, settings.ollama_model)
    return OllamaProbeResponse(
        reachable=status_.reachable,
        ready=status_.ready,
        models=status_.models,
        configured_model=status_.configured_model,
        configured_model_installed=status_.configured_model_installed,
        recommended_model=status_.recommended_model,
        detail=status_.detail,
    )
