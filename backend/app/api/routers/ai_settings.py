"""Admin-only effective AI provider configuration."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentAdmin, _ai_provider
from app.api.schemas.ai_settings import AISettingsResponse, AISettingsUpdateRequest
from app.config import AISettingsUpdate, get_effective_ai_settings, save_effective_ai_settings

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
    return _response(settings)
