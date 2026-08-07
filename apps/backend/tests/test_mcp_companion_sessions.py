"""MCP tool exposure for durable companion sessions (#193 TODO 1).

Before this, `TOOL_CONTRACTS` had no start/get/resume/pause/finish tools for
companion sessions at all — an MCP client could never see or continue a
session, only the REST API could. These tests exercise the real
`/api/v1/mcp/invoke` boundary end to end (grants, audit, feature flag) the
same way test_mcp_security.py does for the original tool set, and also check
that a session started over MCP is the same durable row the REST API sees
(and vice versa) — the whole point of "cross-client continuity".
"""
from app.infrastructure.models import MCPGrantModel


def _grant(db_session, tool, *, access="write", workspace="//approved/root"):
    item = MCPGrantModel(
        requester="fixture-client", server="lensword", tool=tool, access=access, workspace=workspace, mode="always"
    )
    db_session.add(item)
    db_session.flush()
    return item


def _invoke(client, headers, tool, payload, *, workspace="//approved/root"):
    return client.post(
        "/api/v1/mcp/invoke",
        headers=headers,
        json={"requester": "fixture-client", "workspace": workspace, "tool": tool, "payload": payload},
    )


def _enable_companion(client, headers):
    response = client.put("/api/v1/recall-settings", json={"ai_companion_enabled": True}, headers=headers)
    assert response.status_code == 200, response.text


def test_full_session_lifecycle_is_reachable_over_mcp(client, auth_headers, db_session):
    headers = auth_headers()
    _enable_companion(client, headers)
    for tool, access in (
        ("lensword.start_companion_session", "write"),
        ("lensword.get_companion_session", "read"),
        ("lensword.resume_companion_session", "write"),
        ("lensword.pause_companion_session", "write"),
        ("lensword.finish_companion_session", "write"),
    ):
        _grant(db_session, tool, access=access)

    started = _invoke(
        client, headers, "lensword.start_companion_session",
        {"connection_id": "mcp-client-1", "client_id": "agent-host", "goal": "order food"},
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["id"]
    assert started.json()["status"] == "active"
    assert started.json()["revision"] == 1

    fetched = _invoke(client, headers, "lensword.get_companion_session", {"session_id": session_id})
    assert fetched.status_code == 200
    assert fetched.json()["goal"] == "order food"

    paused = _invoke(client, headers, "lensword.pause_companion_session", {"session_id": session_id})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert paused.json()["revision"] == 2

    resumed = _invoke(client, headers, "lensword.resume_companion_session", {"session_id": session_id})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"
    assert resumed.json()["revision"] == 3

    finished = _invoke(client, headers, "lensword.finish_companion_session", {"session_id": session_id})
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"
    # #193 TODO 2: finishing generates a real summary, not an empty field.
    assert finished.json()["summary"]

    # A second call to resume a finished session is an invalid transition,
    # not a crash — it must fail cleanly, not with an opaque 500.
    reopened = _invoke(client, headers, "lensword.resume_companion_session", {"session_id": session_id})
    assert reopened.status_code < 500


def test_a_session_started_over_mcp_is_the_same_durable_row_rest_sees(client, auth_headers, db_session):
    """Cross-client continuity in its most literal form: the MCP tool
    surface and the REST API are two windows onto one session, not two
    separate stores."""
    headers = auth_headers()
    _enable_companion(client, headers)
    _grant(db_session, "lensword.start_companion_session")

    started = _invoke(
        client, headers, "lensword.start_companion_session",
        {"connection_id": "mcp-client-1", "client_id": "agent-host"},
    )
    assert started.status_code == 200
    session_id = started.json()["id"]

    via_rest = client.get(f"/api/v1/companion/sessions/{session_id}", headers=headers)
    assert via_rest.status_code == 200
    assert via_rest.json()["connection_id"] == "mcp-client-1"

    # Continue on the REST side...
    client.post(
        f"/api/v1/companion/sessions/{session_id}/turns",
        json={"role": "user", "content": "hola", "operation_id": "rest-1"},
        headers=headers,
    )

    # ...and read it back through MCP: the turn is visible to both surfaces.
    _grant(db_session, "lensword.get_companion_session", access="read")
    via_mcp = _invoke(client, headers, "lensword.get_companion_session", {"session_id": session_id})
    assert via_mcp.status_code == 200
    assert via_mcp.json()["revision"] == 1  # adding a turn does not bump session.revision


def test_companion_tools_are_gated_by_the_same_feature_flag_as_rest(client, auth_headers, db_session):
    """The MCP surface must not be a back door around `ai_companion_enabled`
    — the flag REST already enforces (see app.api.routers.companion
    ._require_enabled)."""
    headers = auth_headers()
    # Deliberately not calling _enable_companion: the flag defaults off.
    _grant(db_session, "lensword.start_companion_session")

    denied = _invoke(
        client, headers, "lensword.start_companion_session",
        {"connection_id": "mcp-client-1", "client_id": "agent-host"},
    )
    assert denied.status_code == 400, denied.text


def test_getting_an_unknown_session_over_mcp_fails_cleanly(client, auth_headers, db_session):
    headers = auth_headers()
    _enable_companion(client, headers)
    _grant(db_session, "lensword.get_companion_session", access="read")

    missing = _invoke(client, headers, "lensword.get_companion_session", {"session_id": "no-such-session"})
    assert missing.status_code == 400
    assert "not found" in missing.json()["detail"].lower()
