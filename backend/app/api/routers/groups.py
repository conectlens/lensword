from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, GroupRepo, WordRepo
from app.api.mappers import group_summary_to_response, word_to_response
from app.api.schemas.vocabulary import (
    GroupCreateRequest,
    GroupRenameRequest,
    GroupResponse,
    WordCreateRequest,
    WordResponse,
)
from app.application.use_cases.vocabulary import (
    AddWordUseCase,
    CreateGroupUseCase,
    DeleteGroupUseCase,
    GetGroupDetailUseCase,
    ListGroupsUseCase,
    RenameGroupUseCase,
    WordInput,
)
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


@router.get("", response_model=list[GroupResponse])
def list_groups(current_user: CurrentUser, group_repo: GroupRepo, word_repo: WordRepo) -> list[GroupResponse]:
    summaries = ListGroupsUseCase(group_repo, word_repo).execute(current_user.id)
    return [group_summary_to_response(s) for s in summaries]


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupCreateRequest, current_user: CurrentUser, group_repo: GroupRepo, word_repo: WordRepo
) -> GroupResponse:
    group = CreateGroupUseCase(group_repo).execute(current_user.id, payload.name, payload.target_language)
    summaries = ListGroupsUseCase(group_repo, word_repo).execute(current_user.id)
    match = next(s for s in summaries if s.group.id == group.id)
    return group_summary_to_response(match)


@router.get("/{group_id}/words", response_model=list[WordResponse])
def get_group_words(
    group_id: int, current_user: CurrentUser, group_repo: GroupRepo, word_repo: WordRepo
) -> list[WordResponse]:
    try:
        _, words = GetGroupDetailUseCase(group_repo, word_repo).execute(current_user.id, group_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return [word_to_response(w) for w in words]


@router.post("/{group_id}/words", response_model=WordResponse, status_code=status.HTTP_201_CREATED)
def add_word_to_group(
    group_id: int, payload: WordCreateRequest, current_user: CurrentUser, group_repo: GroupRepo, word_repo: WordRepo
) -> WordResponse:
    try:
        word = AddWordUseCase(word_repo, group_repo).execute(
            current_user.id,
            group_id,
            WordInput(
                term=payload.term,
                target_language=payload.target_language,
                translations=payload.translations,
                example_sentence=payload.example_sentence,
                mnemonic=payload.mnemonic,
                category=payload.category,
            ),
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return word_to_response(word)


@router.patch("/{group_id}", response_model=GroupResponse)
def rename_group(
    group_id: int,
    payload: GroupRenameRequest,
    current_user: CurrentUser,
    group_repo: GroupRepo,
    word_repo: WordRepo,
) -> GroupResponse:
    try:
        RenameGroupUseCase(group_repo).execute(current_user.id, group_id, payload.name)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    summaries = ListGroupsUseCase(group_repo, word_repo).execute(current_user.id)
    match = next(s for s in summaries if s.group.id == group_id)
    return group_summary_to_response(match)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, current_user: CurrentUser, group_repo: GroupRepo) -> None:
    try:
        DeleteGroupUseCase(group_repo).execute(current_user.id, group_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
