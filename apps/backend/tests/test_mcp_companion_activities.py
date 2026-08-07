"""MCP tool exposure for measurable companion activities (#194 TODO 1).

Before this, `TOOL_CONTRACTS` had none of the six companion action tools —
an MCP client could never begin, answer, hint, explain, or finish a
structured activity, only the REST API could. Exercises the real
`/api/v1/mcp/invoke` boundary end to end, the same way
test_mcp_companion_sessions.py does for #193's five session tools, and
checks that an activity begun over MCP is the same durable row the REST API
sees.
"""
import uuid

from app.infrastructure.models import MCPGrantModel

# Caller identity is derived server-side from the authenticated bearer token
# (issue #196 TODO 2) — a grant must be bound to the real "user:{id}"
# requester string, not an arbitrary caller-chosen label.
def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _grant(db_session, tool, *, user_id, access="write", workspace="//approved/root"):
    item = MCPGrantModel(
        requester=f"user:{user_id}", server="lensword", tool=tool, access=access, workspace=workspace, mode="always"
    )
    db_session.add(item)
    db_session.flush()
    return item


def _invoke(client, headers, tool, payload, *, workspace="//approved/root"):
    # Mandatory idempotency for writes (issue #196 TODO 4): every write tool
    # contract now requires request_id. Reads have no such field, so it is
    # only injected for tools whose payload doesn't already define one and
    # whose name isn't one of the read-only activity tools.
    payload = dict(payload)
    if tool not in ("lensword_get_activity_result", "lensword_explain_evidence") and "request_id" not in payload:
        payload["request_id"] = str(uuid.uuid4())
    return client.post(
        "/api/v1/mcp/invoke",
        headers=headers,
        json={"workspace": workspace, "tool": tool, "payload": payload},
    )


def _enable_companion(client, headers):
    response = client.put("/api/v1/recall-settings", json={"ai_companion_enabled": True}, headers=headers)
    assert response.status_code == 200, response.text


_ACTIVITY_TOOLS = (
    ("lensword_begin_learning_activity", "write"),
    ("lensword_submit_activity_response", "write"),
    ("lensword_get_activity_result", "read"),
    ("lensword_finish_learning_activity", "write"),
    ("lensword_request_hint", "write"),
    ("lensword_explain_evidence", "read"),
)


def _grant_all(db_session, *, user_id):
    for tool, access in _ACTIVITY_TOOLS:
        _grant(db_session, tool, access=access, user_id=user_id)


def _setup_word(client, headers):
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    return word["id"]


def test_full_activity_lifecycle_is_reachable_over_mcp(client, auth_headers, db_session):
    headers = auth_headers()
    _enable_companion(client, headers)
    _grant_all(db_session, user_id=_user_id(client, headers))
    word_id = _setup_word(client, headers)

    session = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "mcp-client-1", "client_id": "agent-host"},
        headers=headers,
    ).json()

    begun = _invoke(
        client, headers, "lensword_begin_learning_activity",
        {
            "session_id": session["id"], "activity_type": "recall", "prompt": "Recall correr.",
            "expected_evaluation": {"word_id": word_id, "expected_answer": "to run"},
        },
    )
    assert begun.status_code == 200, begun.text
    activity_id = begun.json()["id"]
    assert begun.json()["status"] == "active"
    assert begun.json()["hints_used"] == 0

    hinted = _invoke(client, headers, "lensword_request_hint", {"session_id": session["id"], "activity_id": activity_id})
    assert hinted.status_code == 200, hinted.text
    assert hinted.json()["hints_used"] == 1
    assert hinted.json()["hints_remaining"] == 2

    submitted = _invoke(
        client, headers, "lensword_submit_activity_response",
        {"session_id": session["id"], "activity_id": activity_id, "response": "to run"},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["result"]["correct"] is True

    fetched = _invoke(client, headers, "lensword_get_activity_result", {"session_id": session["id"], "activity_id": activity_id})
    assert fetched.status_code == 200
    assert fetched.json()["response"] == "to run"

    evidence = _invoke(client, headers, "lensword_explain_evidence", {"session_id": session["id"], "activity_id": activity_id})
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["activity_type"] == "recall"

    finished = _invoke(client, headers, "lensword_finish_learning_activity", {"session_id": session["id"], "activity_id": activity_id})
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"

    # A structured recall activity with a word_id must have created exactly
    # one review observation, reachable through the ordinary REST surface
    # (#194 TODO 0/5) — the MCP surface and REST surface see the same fact.
    observations = client.get("/api/v1/me/observations", headers=headers).json()["items"]
    assert len(observations) == 1
    assert observations[0]["word_id"] == word_id


def test_an_activity_begun_over_mcp_is_the_same_durable_row_rest_sees(client, auth_headers, db_session):
    headers = auth_headers()
    _enable_companion(client, headers)
    _grant(db_session, "lensword_begin_learning_activity", user_id=_user_id(client, headers))
    word_id = _setup_word(client, headers)

    session = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "mcp-client-1", "client_id": "agent-host"},
        headers=headers,
    ).json()

    begun = _invoke(
        client, headers, "lensword_begin_learning_activity",
        {
            "session_id": session["id"], "activity_type": "cloze", "prompt": "Fill the blank.",
            "expected_evaluation": {"word_id": word_id},
        },
    )
    assert begun.status_code == 200, begun.text
    activity_id = begun.json()["id"]

    via_rest = client.get(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity_id}", headers=headers
    )
    assert via_rest.status_code == 200
    assert via_rest.json()["id"] == activity_id
    assert via_rest.json()["activity_type"] == "cloze"


def test_free_chat_begun_over_mcp_creates_no_observation_on_submit(client, auth_headers, db_session):
    headers = auth_headers()
    _enable_companion(client, headers)
    _grant_all(db_session, user_id=_user_id(client, headers))

    session = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "mcp-client-1", "client_id": "agent-host"},
        headers=headers,
    ).json()

    begun = _invoke(
        client, headers, "lensword_begin_learning_activity",
        {"session_id": session["id"], "activity_type": "free_chat", "prompt": "Let's chat."},
    )
    assert begun.status_code == 200, begun.text
    activity_id = begun.json()["id"]

    submitted = _invoke(
        client, headers, "lensword_submit_activity_response",
        {"session_id": session["id"], "activity_id": activity_id, "response": "hello there"},
    )
    assert submitted.status_code == 200, submitted.text

    observations = client.get("/api/v1/me/observations", headers=headers).json()["items"]
    assert observations == []


def test_companion_activity_tools_are_gated_by_ai_companion_enabled(client, auth_headers, db_session):
    headers = auth_headers()
    _grant_all(db_session, user_id=_user_id(client, headers))  # deliberately not enabling ai_companion_enabled

    response = _invoke(
        client, headers, "lensword_begin_learning_activity",
        {"session_id": "does-not-matter", "activity_type": "free_chat", "prompt": "hi"},
    )
    assert response.status_code == 400, response.text
