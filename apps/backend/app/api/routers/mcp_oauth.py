"""Remote MCP OAuth: authorization-code + PKCE, scopes, revocation (#196 TODO 1/2/4).

This is the boundary that lets an external MCP host obtain a credential for
a LensWord account WITHOUT ever seeing that account's normal login JWT — the
explicit requirement in issue #196. A remote companion instead gets an
opaque, short-lived access token plus a rotating refresh token, both minted
here, both distinct in shape and signing from `create_access_token` in
infrastructure/security.py (see that separation reasoned about in
app/api/mcp_auth.py's docstring).

Consent (`/authorize`) is a JSON API, not a server-rendered HTML page — this
backend has no page-rendering layer; the SPA frontend calls `GET
/authorize` to fetch what to show the user, then `POST /authorize` with the
user's decision, and receives back the exact redirect URI (with `code` and
`state` attached) to navigate the browser to. That final navigation is what
delivers the code to the native/desktop MCP host waiting on its loopback
redirect URI, exactly as RFC 8252 describes for a public client — the
frontend performing `window.location = redirect_uri` stands in for the
"302 straight from the authorization server" shape a server-rendered
consent page would use.

Every endpoint here is 404 when `settings.remote_mcp_enabled` is False —
the whole remote surface, metadata documents included, does not exist
unless an operator opts in.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, DbSession, rate_limit_mcp_oauth
from app.api.routers.mcp import is_valid_workspace
from app.application.mcp.contracts import TOOL_CONTRACTS
from app.config import get_settings
from app.domain.services.mcp_policy import GrantMode
from app.domain.services.mcp_scopes import MCPScope, SCOPE_TOOLS, parse_scope_string, tools_for_scopes
from app.domain.services.oauth_pkce import SUPPORTED_CODE_CHALLENGE_METHOD, verify_pkce
from app.domain.services.oauth_redirect import is_acceptable_redirect_uri, redirect_uri_matches
from app.domain.value_objects import utcnow
from app.infrastructure.mcp_oauth import (
    hash_token,
    new_access_token,
    new_authorization_code,
    new_client_id,
    new_client_secret,
    new_refresh_token,
    new_token_family_id,
)
from app.infrastructure.models import MCPGrantModel, MCPOAuthAuthorizationCodeModel, MCPOAuthClientModel, MCPOAuthTokenModel

def _require_remote_mcp_enabled() -> None:
    if not get_settings().remote_mcp_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Remote MCP is not enabled on this server")


router = APIRouter(prefix="/api/v1/mcp/oauth", tags=["mcp-oauth"], dependencies=[Depends(_require_remote_mcp_enabled)])
metadata_router = APIRouter(tags=["mcp-oauth"], dependencies=[Depends(_require_remote_mcp_enabled)])

_TOOL_ACCESS = {contract.name: contract.access for contract in TOOL_CONTRACTS}


# --------------------------------------------------------------------------
# Discovery metadata (RFC 9728 protected-resource, RFC 8414 authorization
# server) — the MCP authorization spec requires both be published.
# --------------------------------------------------------------------------


@metadata_router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata() -> dict:
    settings_ = get_settings()
    return {
        "resource": settings_.mcp_issuer_url,
        "authorization_servers": [settings_.mcp_issuer_url],
        "scopes_supported": [scope.value for scope in MCPScope],
        "bearer_methods_supported": ["header"],
    }


@metadata_router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata() -> dict:
    settings_ = get_settings()
    base = settings_.mcp_issuer_url.rstrip("/")
    return {
        "issuer": settings_.mcp_issuer_url,
        "authorization_endpoint": f"{base}/api/v1/mcp/oauth/authorize",
        "token_endpoint": f"{base}/api/v1/mcp/oauth/token",
        "registration_endpoint": f"{base}/api/v1/mcp/oauth/clients",
        "revocation_endpoint": f"{base}/api/v1/mcp/oauth/revoke",
        "scopes_supported": [scope.value for scope in MCPScope],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": [SUPPORTED_CODE_CHALLENGE_METHOD],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
    }


# --------------------------------------------------------------------------
# Dynamic client registration (RFC 7591, minimal subset)
# --------------------------------------------------------------------------


class ClientRegistrationRequest(BaseModel):
    client_name: str = Field(min_length=1, max_length=255)
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    token_endpoint_auth_method: str = Field(default="none", pattern="^(none|client_secret_post)$")

    @field_validator("redirect_uris")
    @classmethod
    def _acceptable_redirect_uris(cls, value: list[str]) -> list[str]:
        if any(not is_acceptable_redirect_uri(uri) for uri in value):
            raise ValueError("every redirect_uri must be https, or http restricted to a loopback host")
        return value


class ClientRegistrationResponse(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str
    client_secret: str | None = None


@router.post("/clients", response_model=ClientRegistrationResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit_mcp_oauth)])
def register_client(payload: ClientRegistrationRequest, db: DbSession) -> ClientRegistrationResponse:
    client_id = new_client_id()
    secret = new_client_secret() if payload.token_endpoint_auth_method == "client_secret_post" else None
    db.add(
        MCPOAuthClientModel(
            client_id=client_id,
            client_name=payload.client_name,
            redirect_uris=payload.redirect_uris,
            client_secret_hash=hash_token(secret) if secret else None,
            created_by_user_id=None,
            created_at=utcnow(),
        )
    )
    db.flush()
    return ClientRegistrationResponse(
        client_id=client_id, client_name=payload.client_name, redirect_uris=payload.redirect_uris,
        token_endpoint_auth_method=payload.token_endpoint_auth_method, client_secret=secret,
    )


# --------------------------------------------------------------------------
# Authorization + consent
# --------------------------------------------------------------------------


def _load_client(db, client_id: str) -> MCPOAuthClientModel:
    client = db.query(MCPOAuthClientModel).filter_by(client_id=client_id).one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")
    return client


def _requester_for(user_id: int, client_id: str) -> str:
    # Must match app.api.mcp_auth.MCPActor.for_oauth exactly — this string
    # is what MCPPolicyGate matches grants against.
    return f"user:{user_id}:client:{client_id}"


class ConsentPreviewResponse(BaseModel):
    client_id: str
    client_name: str
    redirect_uri: str
    workspace: str
    scopes: list[str]
    already_granted_scopes: list[str]
    new_scopes: list[str]


@router.get("/authorize", response_model=ConsentPreviewResponse)
def preview_authorization(
    current_user: CurrentUser, db: DbSession, client_id: str, redirect_uri: str, scope: str, workspace: str,
    response_type: str = "code", code_challenge: str = "", code_challenge_method: str = "", state: str = "",
) -> ConsentPreviewResponse:
    client = _load_client(db, client_id)
    if not redirect_uri_matches(redirect_uri, client.redirect_uris):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="redirect_uri does not match a registered value")
    requested = parse_scope_string(scope)
    if not requested:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_scope")
    requester = _requester_for(current_user.id or 0, client_id)
    existing_tools = {
        item.tool for item in db.query(MCPGrantModel).filter_by(requester=requester, server="lensword", workspace=workspace) if item.revoked_at is None
    }
    already_granted = sorted(
        s.value for s in requested if set(SCOPE_TOOLS.get(s, ())) and set(SCOPE_TOOLS.get(s, ())).issubset(existing_tools)
    )
    new_scopes = sorted(s.value for s in requested if s.value not in already_granted)
    return ConsentPreviewResponse(
        client_id=client_id, client_name=client.client_name, redirect_uri=redirect_uri, workspace=workspace,
        scopes=sorted(s.value for s in requested), already_granted_scopes=already_granted, new_scopes=new_scopes,
    )


class AuthorizeDecisionRequest(BaseModel):
    response_type: str = Field(pattern="^code$")
    client_id: str = Field(min_length=1, max_length=64)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    code_challenge: str = Field(min_length=43, max_length=128)
    code_challenge_method: str = Field(pattern=f"^{SUPPORTED_CODE_CHALLENGE_METHOD}$")
    scope: str = Field(min_length=1, max_length=512)
    workspace: str = Field(min_length=1, max_length=1024)
    state: str = Field(min_length=1, max_length=512)
    approve: bool


class AuthorizeDecisionResponse(BaseModel):
    redirect_uri: str


@router.post("/authorize", response_model=AuthorizeDecisionResponse, dependencies=[Depends(rate_limit_mcp_oauth)])
def decide_authorization(payload: AuthorizeDecisionRequest, current_user: CurrentUser, db: DbSession) -> AuthorizeDecisionResponse:
    client = _load_client(db, payload.client_id)
    if not redirect_uri_matches(payload.redirect_uri, client.redirect_uris):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="redirect_uri does not match a registered value")
    if not payload.approve:
        return AuthorizeDecisionResponse(redirect_uri=f"{payload.redirect_uri}?error=access_denied&state={payload.state}")
    if not is_valid_workspace(payload.workspace):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_workspace")
    requested = parse_scope_string(payload.scope)
    if not requested:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_scope")

    now = utcnow()
    requester = _requester_for(current_user.id or 0, payload.client_id)
    # Provision (or reactivate) an ordinary MCPGrantModel row per tool the
    # approved scopes unlock — the same table/shape /invoke's MCPPolicyGate
    # already enforces for the local path, per issue #196's instruction to
    # extend that machinery rather than build a parallel one.
    for tool in sorted(tools_for_scopes(requested)):
        access = _TOOL_ACCESS[tool].value
        existing = (
            db.query(MCPGrantModel)
            .filter_by(requester=requester, server="lensword", tool=tool, access=access, workspace=payload.workspace)
            .one_or_none()
        )
        if existing is None:
            db.add(MCPGrantModel(requester=requester, server="lensword", tool=tool, access=access, workspace=payload.workspace, mode=GrantMode.ALWAYS.value))
        elif existing.revoked_at is not None:
            existing.revoked_at = None

    code = new_authorization_code()
    db.add(
        MCPOAuthAuthorizationCodeModel(
            code_hash=hash_token(code), client_id=payload.client_id, user_id=current_user.id or 0,
            redirect_uri=payload.redirect_uri, code_challenge=payload.code_challenge,
            code_challenge_method=payload.code_challenge_method, scope=payload.scope, workspace=payload.workspace,
            expires_at=now + timedelta(seconds=get_settings().mcp_authorization_code_ttl_seconds), created_at=now,
        )
    )
    db.flush()
    return AuthorizeDecisionResponse(redirect_uri=f"{payload.redirect_uri}?code={code}&state={payload.state}")


# --------------------------------------------------------------------------
# Token endpoint (RFC 6749 section 4.1.3 / 6, form-encoded per spec)
# --------------------------------------------------------------------------


def _client_secret_ok(client: MCPOAuthClientModel, provided: str | None) -> bool:
    if client.client_secret_hash is None:
        return True  # public client — PKCE is its proof of possession
    return provided is not None and hash_token(provided) == client.client_secret_hash


def _issue_token_pair(db, *, client_id: str, user_id: int, scope: str, workspace: str, family_id: str, rotated_from_id: int | None) -> MCPOAuthTokenModel:
    settings_ = get_settings()
    now = utcnow()
    row = MCPOAuthTokenModel(
        access_token_hash=hash_token(new_access_token_raw := new_access_token()),
        refresh_token_hash=hash_token(new_refresh_token_raw := new_refresh_token()),
        client_id=client_id, user_id=user_id, scope=scope, workspace=workspace,
        access_expires_at=now + timedelta(minutes=settings_.mcp_access_token_ttl_minutes),
        refresh_expires_at=now + timedelta(days=settings_.mcp_refresh_token_ttl_days),
        rotated_from_id=rotated_from_id, family_id=family_id, created_at=now,
    )
    db.add(row)
    db.flush()
    row._raw_access_token = new_access_token_raw  # type: ignore[attr-defined]
    row._raw_refresh_token = new_refresh_token_raw  # type: ignore[attr-defined]
    return row


def _token_response(row: MCPOAuthTokenModel) -> dict:
    return {
        "access_token": row._raw_access_token,  # type: ignore[attr-defined]
        "token_type": "Bearer",
        "expires_in": int((row.access_expires_at - utcnow()).total_seconds()),
        "refresh_token": row._raw_refresh_token,  # type: ignore[attr-defined]
        "scope": row.scope,
    }


@router.post("/token", dependencies=[Depends(rate_limit_mcp_oauth)])
def token(
    db: DbSession,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
) -> dict:
    if grant_type == "authorization_code":
        return _exchange_authorization_code(db, client_id, client_secret, code, redirect_uri, code_verifier)
    if grant_type == "refresh_token":
        return _exchange_refresh_token(db, client_id, client_secret, refresh_token)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported_grant_type")


def _exchange_authorization_code(db, client_id, client_secret, code, redirect_uri, code_verifier) -> dict:
    if not (client_id and code and redirect_uri and code_verifier):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")
    client = _load_client(db, client_id)
    if not _client_secret_ok(client, client_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_client")
    row = db.query(MCPOAuthAuthorizationCodeModel).filter_by(code_hash=hash_token(code)).one_or_none()
    now = utcnow()
    if row is None or row.client_id != client_id or row.consumed_at is not None or row.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
    if row.redirect_uri != redirect_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
    if not verify_pkce(code_verifier, row.code_challenge, row.code_challenge_method):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
    # Single-use (issue #196 TODO 4 replay protection): consumed immediately,
    # inside the same request that validated it, so a raced double-exchange
    # of the same code cannot both succeed.
    row.consumed_at = now
    db.flush()
    issued = _issue_token_pair(
        db, client_id=client_id, user_id=row.user_id, scope=row.scope, workspace=row.workspace,
        family_id=new_token_family_id(), rotated_from_id=None,
    )
    return _token_response(issued)


def _exchange_refresh_token(db, client_id, client_secret, refresh_token_raw) -> dict:
    if not (client_id and refresh_token_raw):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_request")
    client = _load_client(db, client_id)
    if not _client_secret_ok(client, client_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_client")
    row = db.query(MCPOAuthTokenModel).filter_by(refresh_token_hash=hash_token(refresh_token_raw)).one_or_none()
    if row is None or row.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
    now = utcnow()
    if row.revoked_at is not None:
        # Reuse of an already-rotated refresh token (issue #196 TODO 4
        # replay protection, RFC 6749 section 10.4): revoke the entire
        # family immediately, including whatever token this reuse attempt
        # was trying to impersonate its way past.
        db.query(MCPOAuthTokenModel).filter_by(family_id=row.family_id).filter(MCPOAuthTokenModel.revoked_at.is_(None)).update({"revoked_at": now})
        db.flush()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
    if row.refresh_expires_at is None or row.refresh_expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_grant")
    row.revoked_at = now
    db.flush()
    issued = _issue_token_pair(
        db, client_id=client_id, user_id=row.user_id, scope=row.scope, workspace=row.workspace,
        family_id=row.family_id, rotated_from_id=row.id,
    )
    return _token_response(issued)


# --------------------------------------------------------------------------
# Revocation (RFC 7009)
# --------------------------------------------------------------------------


@router.post("/revoke", status_code=status.HTTP_200_OK, dependencies=[Depends(rate_limit_mcp_oauth)])
def revoke(
    db: DbSession, token: Annotated[str, Form()], token_type_hint: Annotated[str | None, Form()] = None
) -> dict:
    now = utcnow()
    digest = hash_token(token)
    row = db.query(MCPOAuthTokenModel).filter(
        (MCPOAuthTokenModel.access_token_hash == digest) | (MCPOAuthTokenModel.refresh_token_hash == digest)
    ).one_or_none()
    if row is not None:
        # Revoking either half revokes the whole family: an access token
        # alone has no refresh token to also invalidate, but the intent of
        # "disconnect this token" is "this credential must stop working
        # now", which for a still-live refresh token means both halves.
        db.query(MCPOAuthTokenModel).filter_by(family_id=row.family_id).filter(MCPOAuthTokenModel.revoked_at.is_(None)).update({"revoked_at": now})
        db.flush()
    # RFC 7009 section 2.2: always 200, whether or not the token was found —
    # an error response here would let a caller probe for valid tokens.
    return {"revoked": True}


# --------------------------------------------------------------------------
# Connection management (issue #196 TODO 3 backing API)
# --------------------------------------------------------------------------


class ConnectionSummary(BaseModel):
    client_id: str
    client_name: str
    scope: str
    workspace: str
    created_at: str
    last_used_at: str | None
    active_token_count: int


@router.get("/connections", response_model=list[ConnectionSummary])
def list_connections(current_user: CurrentUser, db: DbSession) -> list[ConnectionSummary]:
    rows = (
        db.query(MCPOAuthTokenModel)
        .filter_by(user_id=current_user.id)
        .filter(MCPOAuthTokenModel.revoked_at.is_(None))
        .order_by(MCPOAuthTokenModel.created_at.desc())
        .all()
    )
    by_client: dict[str, list[MCPOAuthTokenModel]] = {}
    for row in rows:
        by_client.setdefault(row.client_id, []).append(row)
    clients = {c.client_id: c for c in db.query(MCPOAuthClientModel).filter(MCPOAuthClientModel.client_id.in_(by_client.keys()))}
    summaries = []
    for client_id, tokens in by_client.items():
        newest = max(tokens, key=lambda t: t.created_at)
        last_used = max((t.last_used_at for t in tokens if t.last_used_at is not None), default=None)
        summaries.append(
            ConnectionSummary(
                client_id=client_id, client_name=clients[client_id].client_name if client_id in clients else client_id,
                scope=newest.scope, workspace=newest.workspace, created_at=newest.created_at.isoformat(),
                last_used_at=last_used.isoformat() if last_used else None, active_token_count=len(tokens),
            )
        )
    return summaries


@router.post("/connections/{client_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_connection(client_id: str, current_user: CurrentUser, db: DbSession) -> None:
    now = utcnow()
    # Scoped to current_user.id throughout: a user can only ever name and
    # revoke their own connections, so this needs no separate ownership
    # check beyond the filter itself — there is nothing for another
    # account's client_id to match against here.
    db.query(MCPOAuthTokenModel).filter_by(user_id=current_user.id, client_id=client_id).filter(MCPOAuthTokenModel.revoked_at.is_(None)).update({"revoked_at": now})
    requester = _requester_for(current_user.id or 0, client_id)
    db.query(MCPGrantModel).filter_by(requester=requester).filter(MCPGrantModel.revoked_at.is_(None)).update({"revoked_at": now})
    db.flush()
