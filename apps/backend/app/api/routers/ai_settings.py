"""Admin-only effective AI provider configuration."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentAdmin, _ai_provider
from app.api.schemas.ai_settings import (
    AIProbeResponse,
    AISettingsResponse,
    AISettingsUpdateRequest,
)
from app.config import AISettingsUpdate, Settings, get_effective_ai_settings, save_effective_ai_settings
from app.api.routers.ai import clear_ai_response_cache
from app.infrastructure.ollama_probe import probe_ollama

router = APIRouter(prefix="/api/v1/ai-settings", tags=["AI settings"])


def _response(settings: Settings) -> AISettingsResponse:
    return AISettingsResponse(
        provider=settings.ai_provider,
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        max_output_tokens=settings.ai_max_output_tokens,
        context_max_chars=settings.ai_context_max_chars,
        gemini_model=settings.gemini_model,
        gemini_api_key_set=bool(settings.gemini_api_key),
        vertex_project_id=settings.vertex_project_id,
        vertex_location=settings.vertex_location,
        vertex_model=settings.vertex_model,
        openai_model=settings.openai_model,
        openai_api_key_set=bool(settings.openai_api_key),
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
                gemini_api_key=payload.gemini_api_key,
                gemini_model=payload.gemini_model,
                vertex_project_id=payload.vertex_project_id,
                vertex_location=payload.vertex_location,
                vertex_model=payload.vertex_model,
                openai_api_key=payload.openai_api_key,
                openai_model=payload.openai_model,
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


# Providers whose probe is Ollama's own reachability + model-list check.
# "none" is included so an install with AI switched off still gets that
# check run against whatever OLLAMA_BASE_URL/OLLAMA_MODEL happen to be
# configured — the same thing this endpoint has always done, preserved here
# rather than changed as a side effect of adding the cloud providers.
_OLLAMA_PROBED_PROVIDERS = ("none", "ollama")


@router.get("/probe", response_model=AIProbeResponse)
def probe(_admin: CurrentAdmin) -> AIProbeResponse:
    """Check whether the configured provider looks usable.

    For Ollama (or AI switched off — see _OLLAMA_PROBED_PROVIDERS above),
    this is issue #139's original behaviour: a real reachability + model-list
    request against the local daemon. The three failure modes are reported
    separately — nothing listening, not Ollama, running but no usable model —
    because a single "AI unavailable" would leave someone with Ollama running
    and no model pulled with no idea what to do next.

    For a cloud provider (gemini/vertex/openai), this deliberately does NOT
    make a real generation call: that would be a paid API request fired on
    every admin page load, for a check whose only useful answer here is "is
    a credential configured" — an admin opening this page repeatedly should
    not be billed for it. `live_check_performed=False` on the response marks
    the difference explicitly rather than leaving a caller to assume
    `reachable: true` means "verified against the real API" the way it does
    for Ollama.
    """
    settings = get_effective_ai_settings()
    provider = settings.ai_provider
    if provider in _OLLAMA_PROBED_PROVIDERS:
        status_ = probe_ollama(settings.ollama_base_url, settings.ollama_model)
        return AIProbeResponse(
            provider=provider,
            live_check_performed=True,
            reachable=status_.reachable,
            ready=status_.ready,
            models=status_.models,
            configured_model=status_.configured_model,
            configured_model_installed=status_.configured_model_installed,
            recommended_model=status_.recommended_model,
            detail=status_.detail,
        )
    return _probe_cloud_provider(provider, settings)


def _probe_cloud_provider(provider: str, settings: Settings) -> AIProbeResponse:
    configured, configured_model = {
        "gemini": (bool(settings.gemini_api_key), settings.gemini_model),
        "vertex": (bool(settings.vertex_project_id), settings.vertex_model),
        "openai": (bool(settings.openai_api_key), settings.openai_model),
    }.get(provider, (False, None))
    if configured:
        detail = (
            f"{provider} looks configured. This is a configuration check only — "
            "no request was sent to the provider, so a bad or revoked key would "
            "not be caught here; the first real generation would report that."
        )
    else:
        required = {
            "gemini": "GEMINI_API_KEY",
            "vertex": "VERTEX_PROJECT_ID",
            "openai": "OPENAI_API_KEY",
        }.get(provider, "the provider's required setting")
        detail = f"{provider} is configured as the AI provider, but {required} is not set."
    return AIProbeResponse(
        provider=provider,
        live_check_performed=False,
        reachable=configured,
        ready=configured,
        models=[],
        configured_model=configured_model,
        configured_model_installed=configured,
        recommended_model=configured_model or "",
        detail=detail,
    )
