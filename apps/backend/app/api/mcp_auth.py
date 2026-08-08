"""Authenticated-identity resolution for the MCP invocation boundary (#196).

This is the fix for the issue's headline gap: before this module existed,
`/api/v1/mcp/invoke` read caller identity from `InvokeRequest.requester` —
an ordinary JSON body field any authenticated caller could set to any
string, completely decoupled from who they actually logged in as. Grant
lookups, rate limiting and the audit chain in mcp_policy.py all keyed off
that string, so any account could claim another requester's grants for
policy/audit purposes (data access itself stayed correctly scoped by
`current_user.id`, since dispatcher handlers never read `requester` — but
authorization *decisions*, blame in the audit trail, and per-caller rate
limits all did).

Two paths now resolve to the same `MCPActor` shape, and `mcp.py` never reads
`requester` from the request body again:

* A local companion presenting the user's own login JWT (`LENSWORD_TOKEN` in
  apps/mcp/lensword_mcp/server.py) — unchanged behaviour, just computed
  server-side now instead of trusted from the payload.
* A remote companion presenting an OAuth access token issued by
  mcp_oauth.py — new in #196, and never the user's login JWT (see that
  router's module docstring for why that separation matters).

`MCPActor.requester` is the only thing MCPPolicyGate and the audit chain
ever see as caller identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.api.deps import DbSession, UserRepo, resolve_ai_provider_for_user
from app.domain.services.ai_provider import AIProvider
from app.config import get_settings
from app.domain.entities import User
from app.domain.value_objects import utcnow
from app.infrastructure.mcp_oauth import hash_token
from app.infrastructure.models import MCPOAuthTokenModel
from app.infrastructure.security import decode_access_token

_bearer_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True, slots=True)
class MCPActor:
    user: User
    client_id: str | None
    requester: str

    @staticmethod
    def for_login(user: User) -> "MCPActor":
        return MCPActor(user=user, client_id=None, requester=f"user:{user.id}")

    @staticmethod
    def for_oauth(user: User, client_id: str) -> "MCPActor":
        return MCPActor(user=user, client_id=client_id, requester=f"user:{user.id}:client:{client_id}")


def get_mcp_actor(
    token: Annotated[str | None, Depends(_bearer_scheme)], db: DbSession, user_repo: UserRepo
) -> MCPActor:
    if not token:
        raise _UNAUTHORIZED

    # Try the normal login JWT first. This is the entire local/stdio path
    # and is byte-for-byte the same check `get_current_user` in deps.py
    # already performed before this issue — nothing about it changes.
    subject = decode_access_token(token)
    if subject is not None:
        user = user_repo.get_by_id(int(subject))
        if user is None or not user.is_active:
            raise _UNAUTHORIZED
        return MCPActor.for_login(user)

    # Not a valid login JWT — try it as a remote MCP OAuth access token.
    # Gated on the same flag that disables the whole OAuth router: if an
    # operator turns remote MCP off, any token rows already issued stop
    # working immediately too, rather than lingering as a way in until they
    # naturally expire.
    if not get_settings().remote_mcp_enabled:
        raise _UNAUTHORIZED
    # Looked up by hash; the raw token is never persisted (see
    # infrastructure/mcp_oauth.py's hash_token docstring).
    row = db.query(MCPOAuthTokenModel).filter_by(access_token_hash=hash_token(token)).one_or_none()
    if row is None or row.revoked_at is not None:
        raise _UNAUTHORIZED
    now = utcnow()
    if row.access_expires_at <= now:
        raise _UNAUTHORIZED
    user = user_repo.get_by_id(row.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    row.last_used_at = now
    db.flush()
    return MCPActor.for_oauth(user, row.client_id)


CurrentMCPActor = Annotated[MCPActor, Depends(get_mcp_actor)]


def get_ai_provider_for_actor(actor: CurrentMCPActor, db: DbSession) -> AIProvider | None:
    """The MCP invocation boundary's equivalent of app.api.deps.
    get_ai_provider_for_user — same Bring-Your-Own-Key resolution and
    precedence (see resolve_ai_provider_for_user's own docstring), just
    keyed off MCPActor.user rather than CurrentUser, since mcp.py/
    mcp_plans.py authenticate callers through this module, not deps.py's
    login-JWT-only get_current_user (a remote MCP OAuth access token is
    not a login JWT and get_current_user cannot decode it — see this
    module's own docstring). Defined here rather than in deps.py because
    deps.py cannot import CurrentMCPActor without a circular import: this
    module already imports from deps.py, not the other way around.
    """
    return resolve_ai_provider_for_user(actor.user.id, db)


PerActorAIProvider = Annotated[AIProvider | None, Depends(get_ai_provider_for_actor)]
