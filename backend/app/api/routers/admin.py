from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentAdmin, ReviewSessionRepo, UserRepo, WordRepo
from app.api.schemas.admin import AdminStatsResponse, AdminUserListResponse
from app.application.use_cases.admin import (
    DeleteUserUseCase,
    GetAdminStatsUseCase,
    ListUsersUseCase,
    ReactivateUserUseCase,
    SuspendUserUseCase,
)
from app.domain.exceptions import EntityNotFoundError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStatsResponse)
def get_stats(
    _admin: CurrentAdmin, user_repo: UserRepo, word_repo: WordRepo, session_repo: ReviewSessionRepo
) -> AdminStatsResponse:
    stats = GetAdminStatsUseCase(user_repo, word_repo, session_repo).execute()
    return AdminStatsResponse(**asdict(stats))


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    _admin: CurrentAdmin,
    user_repo: UserRepo,
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminUserListResponse:
    from app.api.routers.auth import _to_user_response

    users = ListUsersUseCase(user_repo).execute(search, limit, offset)
    return AdminUserListResponse(users=[_to_user_response(u) for u in users], total=user_repo.count())


@router.post("/users/{user_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
def suspend_user(user_id: int, _admin: CurrentAdmin, user_repo: UserRepo) -> None:
    try:
        SuspendUserUseCase(user_repo).execute(user_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/users/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
def reactivate_user(user_id: int, _admin: CurrentAdmin, user_repo: UserRepo) -> None:
    try:
        ReactivateUserUseCase(user_repo).execute(user_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, _admin: CurrentAdmin, user_repo: UserRepo) -> None:
    try:
        DeleteUserUseCase(user_repo).execute(user_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
