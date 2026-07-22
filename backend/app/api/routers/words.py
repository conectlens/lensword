from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, GroupRepo, WordRepo
from app.api.mappers import word_to_response
from app.api.schemas.vocabulary import WordAssociationsUpdateRequest, WordCreateRequest, WordResponse
from app.application.use_cases.vocabulary import (
    DeleteWordUseCase,
    GetWordUseCase,
    UpdateWordAssociationsUseCase,
    UpdateWordUseCase,
    WordInput,
)
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError

router = APIRouter(prefix="/api/v1/words", tags=["words"])


def _handle_common_errors(exc: Exception):
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    raise exc


@router.get("/{word_id}", response_model=WordResponse)
def get_word(word_id: int, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo) -> WordResponse:
    try:
        word = GetWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return word_to_response(word)


@router.put("/{word_id}", response_model=WordResponse)
def update_word(
    word_id: int, payload: WordCreateRequest, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo
) -> WordResponse:
    try:
        word = UpdateWordUseCase(word_repo, group_repo).execute(
            current_user.id,
            word_id,
            WordInput(
                term=payload.term,
                target_language=payload.target_language,
                translations=payload.translations,
                example_sentence=payload.example_sentence,
                mnemonic=payload.mnemonic,
                category=payload.category,
            ),
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return word_to_response(word)


@router.patch("/{word_id}/associations", response_model=WordResponse)
def update_associations(
    word_id: int,
    payload: WordAssociationsUpdateRequest,
    current_user: CurrentUser,
    word_repo: WordRepo,
    group_repo: GroupRepo,
) -> WordResponse:
    try:
        word = UpdateWordAssociationsUseCase(word_repo, group_repo).execute(
            current_user.id,
            word_id,
            add=[(e.kind, e.value) for e in payload.add],
            remove=[(e.kind, e.value) for e in payload.remove],
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return word_to_response(word)


@router.delete("/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_word(word_id: int, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo) -> None:
    try:
        DeleteWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
