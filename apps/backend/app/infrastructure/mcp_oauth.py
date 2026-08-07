"""Token/id/secret generation for the remote MCP OAuth flow (issue #196).

Randomness makes this infrastructure, not a domain service (see the module
docstrings on oauth_pkce.py and mcp_scopes.py for the "pure domain services
have zero I/O" line this repo draws). `secrets` is stdlib and already the
right tool: every value here is an opaque bearer credential, never parsed,
so there is no reason to reach for a JWT library the way `create_access_token`
does for the *login* token this deliberately does not reuse.
"""
from __future__ import annotations

import hashlib
import secrets


def hash_token(raw: str) -> str:
    """SHA-256 of a bearer credential, for at-rest storage and lookup.

    Never store the raw token: a read of this table (a backup, a logging
    pipeline, a compromised replica) must not itself hand out live
    credentials. Lookups hash the presented token and compare hashes, the
    same shape MCPIdempotencyKeyModel and MCPOAuthAuthorizationCodeModel use.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_access_token() -> str:
    return f"lwmcp_at_{secrets.token_urlsafe(32)}"


def new_refresh_token() -> str:
    return f"lwmcp_rt_{secrets.token_urlsafe(32)}"


def new_authorization_code() -> str:
    return secrets.token_urlsafe(32)


def new_client_id() -> str:
    return f"lwmcp_client_{secrets.token_urlsafe(12)}"


def new_client_secret() -> str:
    return secrets.token_urlsafe(32)


def new_token_family_id() -> str:
    """Groups every access/refresh pair descended from one authorization
    code (through rotation) so reuse of an already-rotated refresh token can
    revoke the whole lineage in one query — see MCPOAuthTokenModel's
    docstring."""
    return secrets.token_hex(16)
