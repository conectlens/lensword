"""Remote MCP OAuth: code+PKCE, scopes, revocation, and adversarial cases.

Covers issue #196's success metric end to end (register a client, complete
OAuth, invoke one approved tool, get denied an unapproved one, revoke and
be blocked immediately) plus the abuse scenarios TODO 4 asks for:
token substitution, refresh-token replay, and cross-user grant reuse.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.infrastructure.models import MCPOAuthTokenModel


@pytest.fixture()
def remote_mcp_enabled(monkeypatch):
    monkeypatch.setenv("REMOTE_MCP_ENABLED", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("REMOTE_MCP_ENABLED", raising=False)
    get_settings.cache_clear()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:100]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _register_client(client, *, redirect_uri="https://companion.example/callback", auth_method="none"):
    response = client.post(
        "/api/v1/mcp/oauth/clients",
        json={"client_name": "Test Companion", "redirect_uris": [redirect_uri], "token_endpoint_auth_method": auth_method},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _authorize(client, headers, *, client_id, redirect_uri, scope, challenge, workspace="/approved", state="xyz"):
    decision = client.post(
        "/api/v1/mcp/oauth/authorize",
        headers=headers,
        json={
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge": challenge, "code_challenge_method": "S256", "scope": scope,
            "workspace": workspace, "state": state, "approve": True,
        },
    )
    assert decision.status_code == 200, decision.text
    parsed = urlparse(decision.json()["redirect_uri"])
    query = parse_qs(parsed.query)
    assert query["state"] == [state]
    return query["code"][0]


def _exchange_code(client, *, client_id, redirect_uri, code, verifier, client_secret=None):
    form = {"grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect_uri, "code": code, "code_verifier": verifier}
    if client_secret:
        form["client_secret"] = client_secret
    return client.post("/api/v1/mcp/oauth/token", data=form)


def _full_flow(client, headers, *, scope="vocabulary-read", workspace="/approved"):
    registration = _register_client(client)
    client_id, redirect_uri = registration["client_id"], registration["redirect_uris"][0]
    verifier, challenge = _pkce_pair()
    code = _authorize(client, headers, client_id=client_id, redirect_uri=redirect_uri, scope=scope, challenge=challenge, workspace=workspace)
    token_response = _exchange_code(client, client_id=client_id, redirect_uri=redirect_uri, code=code, verifier=verifier)
    assert token_response.status_code == 200, token_response.text
    return client_id, redirect_uri, token_response.json()


# --------------------------------------------------------------------------
# Disabled by default
# --------------------------------------------------------------------------


def test_oauth_surface_is_404_until_remote_mcp_is_enabled(client):
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404
    assert client.get("/.well-known/oauth-protected-resource").status_code == 404
    assert client.post("/api/v1/mcp/oauth/clients", json={"client_name": "x", "redirect_uris": ["https://x.example/cb"]}).status_code == 404


# --------------------------------------------------------------------------
# Discovery metadata
# --------------------------------------------------------------------------


def test_metadata_documents_advertise_pkce_and_the_real_scope_vocabulary(client, remote_mcp_enabled):
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert as_metadata["code_challenge_methods_supported"] == ["S256"]
    assert as_metadata["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert set(as_metadata["scopes_supported"]) == {
        "profile-read", "vocabulary-read", "session-read", "progress-read",
        "conversation-write", "review-write", "card-write", "context-import",
    }
    resource_metadata = client.get("/.well-known/oauth-protected-resource").json()
    assert resource_metadata["authorization_servers"] == [resource_metadata["resource"]]


def test_authorization_endpoint_points_at_the_frontend_not_this_api(client, remote_mcp_enabled):
    """A connector's browser redirect must land somewhere that can actually
    render a login/consent screen — this API's own /authorize is a
    Bearer-token JSON endpoint no browser navigation can call. Reproduces
    the "Could not validate credentials" failure a real Claude.ai connection
    hit in production: the metadata used to advertise this API's own URL."""
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert as_metadata["authorization_endpoint"] == get_settings().mcp_consent_url
    assert "/api/v1/mcp/oauth/authorize" not in as_metadata["authorization_endpoint"]


# --------------------------------------------------------------------------
# Remote grants with no `workspace` (no external OAuth client sends one —
# it names this app's local-filesystem sandboxing concept, not anything an
# RFC 8707 `resource` parameter maps to; see mcp_remote_workspace's
# docstring in app/config.py)
# --------------------------------------------------------------------------


def test_is_valid_workspace_accepts_the_configured_remote_value(monkeypatch):
    from app.api.routers.mcp import is_valid_workspace

    monkeypatch.setenv("MCP_REMOTE_WORKSPACE", "a-custom-remote-tag")
    get_settings.cache_clear()
    try:
        assert is_valid_workspace("a-custom-remote-tag") is True
        # Still rejects an arbitrary non-path string that merely isn't the
        # configured value — this isn't "any string is now fine".
        assert is_valid_workspace("some-other-tag") is False
        # The local-workspace rule (absolute POSIX path, no "..") is
        # untouched by this special case.
        assert is_valid_workspace("/approved") is True
        assert is_valid_workspace("relative/path") is False
    finally:
        monkeypatch.delenv("MCP_REMOTE_WORKSPACE", raising=False)
        get_settings.cache_clear()


def test_preview_authorization_defaults_workspace_when_the_client_omits_it(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    registration = _register_client(client)
    client_id, redirect_uri = registration["client_id"], registration["redirect_uris"][0]

    preview = client.get(
        "/api/v1/mcp/oauth/authorize",
        headers=headers,
        params={"client_id": client_id, "redirect_uri": redirect_uri, "scope": "vocabulary-read"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["workspace"] == get_settings().mcp_remote_workspace


def test_full_remote_flow_with_no_workspace_anywhere_in_the_request(client, auth_headers, remote_mcp_enabled):
    """The exact shape of a real Claude.ai connection: registration, then
    authorize/token/invoke with `workspace` never once supplied — reproduces
    the request that originally failed against this endpoint in production."""
    headers = auth_headers()
    registration = _register_client(client)
    client_id, redirect_uri = registration["client_id"], registration["redirect_uris"][0]
    verifier, challenge = _pkce_pair()

    decision = client.post(
        "/api/v1/mcp/oauth/authorize",
        headers=headers,
        json={
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge": challenge, "code_challenge_method": "S256", "scope": "vocabulary-read",
            "state": "xyz", "approve": True,
            # workspace deliberately omitted
        },
    )
    assert decision.status_code == 200, decision.text
    code = parse_qs(urlparse(decision.json()["redirect_uri"]).query)["code"][0]

    token_response = _exchange_code(client, client_id=client_id, redirect_uri=redirect_uri, code=code, verifier=verifier)
    assert token_response.status_code == 200, token_response.text
    access_headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

    invoked = client.post(
        "/api/v1/mcp/invoke", headers=access_headers,
        json={"tool": "lensword.search_words", "workspace": get_settings().mcp_remote_workspace, "payload": {"query": "hola"}},
    )
    assert invoked.status_code == 200, invoked.text

    # The grant is genuinely scoped to the resolved workspace, not
    # unconditionally accepted regardless of it — a tool call claiming a
    # different workspace must still be denied.
    wrong_workspace = client.post(
        "/api/v1/mcp/invoke", headers=access_headers,
        json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": "hola"}},
    )
    assert wrong_workspace.status_code == 403


# --------------------------------------------------------------------------
# Client registration
# --------------------------------------------------------------------------


def test_registration_rejects_a_non_loopback_http_redirect_uri(client, remote_mcp_enabled):
    response = client.post(
        "/api/v1/mcp/oauth/clients",
        json={"client_name": "Bad Client", "redirect_uris": ["http://attacker.example/callback"]},
    )
    assert response.status_code == 422


def test_registration_accepts_https_and_loopback_http(client, remote_mcp_enabled):
    response = client.post(
        "/api/v1/mcp/oauth/clients",
        json={"client_name": "Native Host", "redirect_uris": ["https://good.example/cb", "http://127.0.0.1:51000/cb"]},
    )
    assert response.status_code == 201


# --------------------------------------------------------------------------
# End-to-end success metric: OAuth, one scoped resource, one approved tool
# --------------------------------------------------------------------------


def test_full_flow_completes_oauth_reads_a_resource_and_invokes_one_tool(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    _client_id, _redirect_uri, tokens = _full_flow(client, headers, scope="vocabulary-read session-read")
    access_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resource = client.get("/api/v1/mcp/resource", headers=access_headers, params={"uri": "lensword://me/due", "workspace": "/approved"})
    assert resource.status_code == 200

    invoked = client.post(
        "/api/v1/mcp/invoke", headers=access_headers,
        json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": "hola"}},
    )
    assert invoked.status_code == 200


def test_unapproved_scope_is_denied_even_with_a_valid_token(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    _client_id, _redirect_uri, tokens = _full_flow(client, headers, scope="vocabulary-read")
    access_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    denied = client.post(
        "/api/v1/mcp/invoke", headers=access_headers,
        json={"tool": "lensword.get_due_reviews", "workspace": "/approved", "payload": {}},
    )
    assert denied.status_code == 403 and denied.json()["detail"] == "no_grant"


def test_revocation_blocks_subsequent_calls_immediately(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    client_id, _redirect_uri, tokens = _full_flow(client, headers)
    access_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/api/v1/mcp/invoke", headers=access_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}}).status_code == 200

    revoked = client.post(f"/api/v1/mcp/oauth/connections/{client_id}/revoke", headers=headers)
    assert revoked.status_code == 204

    blocked = client.post("/api/v1/mcp/invoke", headers=access_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}})
    assert blocked.status_code == 401


def test_revoke_endpoint_immediately_kills_the_access_token_too(client, auth_headers, remote_mcp_enabled):
    """RFC 7009: revoking a refresh token (or the pair) must not leave the
    still-unexpired access token usable."""
    headers = auth_headers()
    _client_id, _redirect_uri, tokens = _full_flow(client, headers)
    revoke_response = client.post("/api/v1/mcp/oauth/revoke", data={"token": tokens["refresh_token"]})
    assert revoke_response.status_code == 200

    access_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    blocked = client.post("/api/v1/mcp/invoke", headers=access_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}})
    assert blocked.status_code == 401


# --------------------------------------------------------------------------
# TODO 4 adversarial cases
# --------------------------------------------------------------------------


def test_pkce_mismatch_is_rejected(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    registration = _register_client(client)
    client_id, redirect_uri = registration["client_id"], registration["redirect_uris"][0]
    verifier, challenge = _pkce_pair()
    code = _authorize(client, headers, client_id=client_id, redirect_uri=redirect_uri, scope="vocabulary-read", challenge=challenge)
    wrong_verifier, _ = _pkce_pair()
    response = _exchange_code(client, client_id=client_id, redirect_uri=redirect_uri, code=code, verifier=wrong_verifier)
    assert response.status_code == 400 and response.json()["detail"] == "invalid_grant"


def test_authorization_code_is_single_use(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    registration = _register_client(client)
    client_id, redirect_uri = registration["client_id"], registration["redirect_uris"][0]
    verifier, challenge = _pkce_pair()
    code = _authorize(client, headers, client_id=client_id, redirect_uri=redirect_uri, scope="vocabulary-read", challenge=challenge)
    first = _exchange_code(client, client_id=client_id, redirect_uri=redirect_uri, code=code, verifier=verifier)
    assert first.status_code == 200
    replay = _exchange_code(client, client_id=client_id, redirect_uri=redirect_uri, code=code, verifier=verifier)
    assert replay.status_code == 400 and replay.json()["detail"] == "invalid_grant"


def test_redirect_uri_mismatch_at_token_exchange_is_rejected(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    registration = _register_client(client, redirect_uri="https://companion.example/callback")
    client_id = registration["client_id"]
    verifier, challenge = _pkce_pair()
    code = _authorize(client, headers, client_id=client_id, redirect_uri="https://companion.example/callback", scope="vocabulary-read", challenge=challenge)
    response = _exchange_code(client, client_id=client_id, redirect_uri="https://companion.example/callback/../evil", code=code, verifier=verifier)
    assert response.status_code == 400


def test_authorize_rejects_a_redirect_uri_that_was_not_registered(client, auth_headers, remote_mcp_enabled):
    headers = auth_headers()
    registration = _register_client(client, redirect_uri="https://companion.example/callback")
    verifier, challenge = _pkce_pair()
    response = client.post(
        "/api/v1/mcp/oauth/authorize", headers=headers,
        json={
            "response_type": "code", "client_id": registration["client_id"], "redirect_uri": "https://attacker.example/callback",
            "code_challenge": challenge, "code_challenge_method": "S256", "scope": "vocabulary-read",
            "workspace": "/approved", "state": "s", "approve": True,
        },
    )
    assert response.status_code == 400


def test_refresh_token_rotation_and_reuse_revokes_the_whole_family(client, auth_headers, remote_mcp_enabled):
    """RFC 6749 section 10.4 replay protection: reusing an old refresh token
    after it has already been rotated must revoke the entire lineage,
    including whatever token the rotation legitimately produced."""
    headers = auth_headers()
    client_id, redirect_uri, tokens = _full_flow(client, headers)

    rotated = client.post("/api/v1/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    new_tokens = rotated.json()
    assert new_tokens["access_token"] != tokens["access_token"]

    # The new access token works.
    new_headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
    assert client.post("/api/v1/mcp/invoke", headers=new_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}}).status_code == 200

    # Reusing the OLD (already-rotated) refresh token is a replay attempt.
    replay = client.post("/api/v1/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 400 and replay.json()["detail"] == "invalid_grant"

    # The whole family — including the token issued by the legitimate
    # rotation above — is now revoked as a precaution.
    blocked = client.post("/api/v1/mcp/invoke", headers=new_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}})
    assert blocked.status_code == 401


def test_a_stale_or_wrong_token_cannot_be_substituted_into_another_clients_flow(client, auth_headers, remote_mcp_enabled):
    """Token-substitution / confused-deputy: a token minted for one
    client_id must not authenticate a refresh against a different client_id."""
    headers = auth_headers()
    client_id_a, _redirect_a, tokens_a = _full_flow(client, headers)
    registration_b = _register_client(client, redirect_uri="https://other-companion.example/callback")

    cross = client.post("/api/v1/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": registration_b["client_id"], "refresh_token": tokens_a["refresh_token"]})
    assert cross.status_code == 400 and cross.json()["detail"] == "invalid_grant"


def test_two_accounts_authorizing_the_same_client_get_independently_scoped_grants(client, auth_headers, remote_mcp_enabled):
    """Cross-user isolation: account B must not be able to discover or
    access account A's resources through a shared client_id."""
    alice = auth_headers(username="oauth-alice", email="oauth-alice@example.com")
    bob = auth_headers(username="oauth-bob", email="oauth-bob@example.com")

    registration = _register_client(client)
    client_id, redirect_uri = registration["client_id"], registration["redirect_uris"][0]

    verifier_a, challenge_a = _pkce_pair()
    code_a = _authorize(client, alice, client_id=client_id, redirect_uri=redirect_uri, scope="vocabulary-read", challenge=challenge_a)
    tokens_a = _exchange_code(client, client_id=client_id, redirect_uri=redirect_uri, code=code_a, verifier=verifier_a).json()

    # Bob never completed his own authorization — his account has no grant
    # for this client at all.
    bob_headers = {"Authorization": f"Bearer {tokens_a['access_token']}"}
    # Alice's token still only works for Alice; there is nothing for Bob to
    # substitute it with, so this just re-confirms it is Alice's token, not
    # a token bound to "whoever holds it".
    assert client.post("/api/v1/mcp/invoke", headers=bob_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}}).status_code == 200

    connections_alice = client.get("/api/v1/mcp/oauth/connections", headers=alice).json()
    connections_bob = client.get("/api/v1/mcp/oauth/connections", headers=bob).json()
    assert len(connections_alice) == 1 and connections_bob == []


def test_requester_identity_for_oauth_actors_encodes_user_and_client(client, auth_headers, db_session, remote_mcp_enabled):
    headers = auth_headers()
    user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
    client_id, _redirect_uri, tokens = _full_flow(client, headers)
    access_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    client.post("/api/v1/mcp/invoke", headers=access_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}})

    from app.infrastructure.models import MCPAuditEventModel

    audit = db_session.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id.desc()).first()
    assert audit.requester == f"user:{user_id}:client:{client_id}"


def test_disabling_remote_mcp_immediately_invalidates_existing_oauth_tokens(client, auth_headers, db_session, remote_mcp_enabled, monkeypatch):
    headers = auth_headers()
    _client_id, _redirect_uri, tokens = _full_flow(client, headers)
    access_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/api/v1/mcp/invoke", headers=access_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}}).status_code == 200

    monkeypatch.setenv("REMOTE_MCP_ENABLED", "false")
    get_settings.cache_clear()
    try:
        blocked = client.post("/api/v1/mcp/invoke", headers=access_headers, json={"tool": "lensword.search_words", "workspace": "/approved", "payload": {"query": ""}})
        assert blocked.status_code == 401
    finally:
        monkeypatch.setenv("REMOTE_MCP_ENABLED", "true")
        get_settings.cache_clear()


def test_token_row_never_persists_the_raw_bearer_credential(client, auth_headers, db_session, remote_mcp_enabled):
    headers = auth_headers()
    _client_id, _redirect_uri, tokens = _full_flow(client, headers)
    row = db_session.query(MCPOAuthTokenModel).order_by(MCPOAuthTokenModel.id.desc()).first()
    assert tokens["access_token"] not in row.access_token_hash
    assert tokens["refresh_token"] not in (row.refresh_token_hash or "")
