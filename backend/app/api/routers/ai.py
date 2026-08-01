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
from app.domain.services.ai_provider import AIProvider, WordEnrichment

router = APIRouter(prefix="/api/v1/ai", tags=["AI vocabulary"])


def _provider(provider: AIProvider | None) -> AIProvider:
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(AIProviderNotConfiguredError()))
    return provider


def _response(value: WordEnrichment) -> WordEnrichmentResponse:
    return WordEnrichmentResponse(**{field: getattr(value, field) for field in WordEnrichmentResponse.model_fields})


async def _enrich(provider: AIProvider, payload: EnrichWordRequest) -> WordEnrichmentResponse:
    try:
        return _response(await provider.enrich_word(payload.term, payload.source_language, payload.target_language))
    except AIProviderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/enrich", response_model=WordEnrichmentResponse)
async def enrich_word(payload: EnrichWordRequest, _user: CurrentUser, provider: OptionalAIProvider) -> WordEnrichmentResponse:
    return await _enrich(_provider(provider), payload)


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
