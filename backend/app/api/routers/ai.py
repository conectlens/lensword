"""Authenticated Phase-1 AI vocabulary endpoints."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, OptionalAIProvider
from app.api.schemas.ai import (
    EnrichWordRequest,
    GenerateExamplesRequest,
    RegeneratedFieldResponse,
    RegenerateFieldRequest,
    TranslateInContextRequest,
    WordEnrichmentResponse,
)
from app.domain.exceptions import AIProviderNotConfiguredError, AIProviderUnavailableError
from app.config import get_effective_ai_settings
from app.domain.services.ai_cache import AIResponseCache, CacheKey
from app.domain.services.ai_provider import AIProvider, WordEnrichment
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/ai", tags=["AI vocabulary"])

# One cache per process, shared across requests but never across users — the
# key carries the account id (#139). A local model takes seconds per
# generation, and asking it the same question twice in a minute is the
# difference between a feature that feels instant and one nobody waits for.
_cache = AIResponseCache()


def clear_ai_response_cache() -> None:
    """Drop every cached response. Called when the AI settings change."""
    _cache.clear()


def _cache_key(user_id: int, operation: str, payload: dict) -> CacheKey:
    """Key an AI call.

    The provider and model are read from the effective settings rather than
    passed in, so a response can never outlive the configuration that produced
    it: switching model changes the key, and the old answers become
    unreachable rather than wrong.
    """
    settings = get_effective_ai_settings()
    return CacheKey.build(
        user_id=user_id,
        provider=settings.ai_provider or "none",
        model=settings.ollama_model or "none",
        operation=operation,
        payload=payload,
    )


def _provider(provider: AIProvider | None) -> AIProvider:
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(AIProviderNotConfiguredError()))
    return provider


def _response(value: WordEnrichment) -> WordEnrichmentResponse:
    return WordEnrichmentResponse(**{field: getattr(value, field) for field in WordEnrichmentResponse.model_fields})


async def _enrich(
    provider: AIProvider, payload: EnrichWordRequest, user_id: int | None = None
) -> WordEnrichmentResponse:
    key = None
    if user_id is not None:
        key = _cache_key(
            user_id,
            "enrich",
            {
                "term": payload.term,
                "source": payload.source_language,
                "target": payload.target_language,
            },
        )
        cached = _cache.get(key, utcnow())
        if cached is not None:
            return cached

    try:
        result = _response(
            await provider.enrich_word(payload.term, payload.source_language, payload.target_language)
        )
    except AIProviderUnavailableError as exc:
        # Deliberately not cached. A model that was unreachable a minute ago
        # may be running now, and caching the failure would keep a working
        # system broken for the length of the TTL.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    if key is not None:
        _cache.put(key, result, utcnow())
    return result


@router.post("/enrich", response_model=WordEnrichmentResponse)
async def enrich_word(payload: EnrichWordRequest, current_user: CurrentUser, provider: OptionalAIProvider) -> WordEnrichmentResponse:
    return await _enrich(_provider(provider), payload, current_user.id)


@router.post("/translate-in-context", response_model=WordEnrichmentResponse)
async def translate_in_context(
    payload: TranslateInContextRequest, _user: CurrentUser, provider: OptionalAIProvider
) -> WordEnrichmentResponse:
    try:
        return _response(
            await _provider(provider).translate_in_context(
                payload.word, payload.sentence, payload.source_language, payload.target_language
            )
        )
    except AIProviderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/examples", response_model=WordEnrichmentResponse)
async def generate_examples(
    payload: GenerateExamplesRequest, _user: CurrentUser, provider: OptionalAIProvider
) -> WordEnrichmentResponse:
    context = "; ".join(value for value in (payload.interests, payload.profession, payload.topic) if value)
    try:
        return _response(
            await _provider(provider).enrich_word(
                f"{payload.term} ({context})" if context else payload.term,
                payload.source_language,
                payload.target_language,
            )
        )
    except AIProviderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/regenerate-field", response_model=RegeneratedFieldResponse)
async def regenerate_field(
    payload: RegenerateFieldRequest, _user: CurrentUser, provider: OptionalAIProvider
) -> RegeneratedFieldResponse:
    try:
        value = await _provider(provider).generate_field(
            payload.field, payload.term, payload.source_language, payload.target_language, payload.context
        )
    except AIProviderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return RegeneratedFieldResponse(field=payload.field, value=value)
