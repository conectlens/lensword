from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentAdmin, DbSession, ReviewSessionRepo, UserRepo, WordRepo
from app.api.schemas.admin import AdminStatsResponse, AdminUserListResponse, MCPAuditResponse, MCPGrantRequest, MCPGrantResponse
from app.application.use_cases.admin import (
    DeleteUserUseCase,
    GetAdminStatsUseCase,
    ListUsersUseCase,
    ReactivateUserUseCase,
    SuspendUserUseCase,
)
from app.domain.exceptions import EntityNotFoundError
from app.domain.value_objects import utcnow
from app.infrastructure.models import MCPAuditEventModel, MCPGrantModel

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


@router.get("/mcp/grants", response_model=list[MCPGrantResponse])
def list_mcp_grants(_admin: CurrentAdmin, db: DbSession) -> list[MCPGrantResponse]:
    return [MCPGrantResponse(id=item.id, requester=item.requester, server=item.server, tool=item.tool, access=item.access, workspace=item.workspace, mode=item.mode, expires_at=item.expires_at, revoked_at=item.revoked_at) for item in db.query(MCPGrantModel).order_by(MCPGrantModel.id.desc())]

@router.post("/mcp/grants", response_model=MCPGrantResponse, status_code=status.HTTP_201_CREATED)
def create_mcp_grant(payload: MCPGrantRequest, _admin: CurrentAdmin, db: DbSession) -> MCPGrantResponse:
    item = MCPGrantModel(**payload.model_dump())
    db.add(item); db.flush()
    return MCPGrantResponse(id=item.id, revoked_at=item.revoked_at, **payload.model_dump())

@router.post("/mcp/grants/{grant_id}/revoke", response_model=MCPGrantResponse)
def revoke_mcp_grant(grant_id: int, _admin: CurrentAdmin, db: DbSession) -> MCPGrantResponse:
    item = db.get(MCPGrantModel, grant_id)
    if item is None: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP grant was not found")
    item.revoked_at = utcnow(); db.flush()
    return MCPGrantResponse(id=item.id, requester=item.requester, server=item.server, tool=item.tool, access=item.access, workspace=item.workspace, mode=item.mode, expires_at=item.expires_at, revoked_at=item.revoked_at)

@router.get("/mcp/audit", response_model=list[MCPAuditResponse])
def list_mcp_audit(_admin: CurrentAdmin, db: DbSession) -> list[MCPAuditResponse]:
    return [MCPAuditResponse(id=item.id, requester=item.requester, tool=item.tool, decision=item.decision, event=item.event, event_hash=item.event_hash, created_at=item.created_at) for item in db.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id.desc()).limit(200)]
