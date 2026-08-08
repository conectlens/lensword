from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, GroupRepo, PerUserAIProvider
from app.api.schemas.extract import (
    ExtractedVocabularyResponse,
    ExtractVocabularyDisabled,
    ExtractVocabularyOk,
    ExtractVocabularyRequest,
    ExtractVocabularyResponse,
    ExtractVocabularyUnavailable,
)
from app.application.use_cases.extract import ExtractVocabularyUseCase
from app.config import get_settings
from app.domain.exceptions import AIProviderNotConfiguredError, AIProviderUnavailableError, EntityNotFoundError, PermissionDeniedError

router = APIRouter(prefix="/api/v1/extract", tags=["vocabulary extraction"])


@router.post("", response_model=ExtractVocabularyResponse)
async def extract_vocabulary(
    payload: ExtractVocabularyRequest,
    current_user: CurrentUser,
    group_repo: GroupRepo,
    provider: PerUserAIProvider,
) -> ExtractVocabularyResponse:
    use_case = ExtractVocabularyUseCase(
        group_repo,
        provider,
        fallback_enabled=get_settings().ai_extract_fallback_enabled,
    )
    try:
        items, source = await use_case.execute(
            current_user.id,
            payload.group_id,
            payload.text,
            payload.source_language,
            payload.target_language,
            payload.max_items,
            payload.min_level,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AIProviderNotConfiguredError:
        return ExtractVocabularyDisabled()
    except AIProviderUnavailableError as exc:
        return ExtractVocabularyUnavailable(detail=str(exc))
    return ExtractVocabularyOk(
        source=source,
        items=[ExtractedVocabularyResponse(term=item.term, translations=item.translations, examples=item.examples, cefr_level=item.cefr_level) for item in items],
    )
