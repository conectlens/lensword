"""Issue #199 TODO 2: cross-user resource enumeration over the MCP boundary.

`tests/test_tenant_isolation.py` exempts the whole `/api/v1/mcp` prefix from
its `CROSS_TENANT_CASES` battery (see that file's `_EXEMPT_PREFIXES`), on the
stated grounds that MCP has "its own grant/scope model and its own tests"
(test_mcp_security.py, test_mcp_policy.py). Those files prove account B
cannot invoke a tool without a grant of *B's own* — but they never prove
account B, holding a real grant for a tool, cannot use that grant plus a
guessed-or-observed session/task id belonging to account A to read or
mutate A's own companion session/task. The underlying use cases
(`GetCompanionSessionUseCase`, `TransitionCompanionSessionUseCase`,
`SqlAlchemyCompanionTaskRepository.get`) already scope every lookup by
`user_id`, and `test_tenant_isolation.py`'s own `CROSS_TENANT_CASES` proves
this holds for the REST surface reaching the same use cases/repositories —
this file closes the same question specifically for the MCP tool surface
(`/api/v1/mcp/invoke`), which goes through an entirely different code path
first (MCPPolicyGate, grants, the dispatcher) before ever reaching those use
cases, so the REST-side proof does not by itself cover it.
"""
from __future__ import annotations

import uuid

from app.infrastructure.models import MCPGrantModel


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _enable_companion(client, headers) -> None:
    response = client.put("/api/v1/recall-settings", json={"ai_companion_enabled": True}, headers=headers)
    assert response.status_code == 200, response.text


def _grant(db_session, tool, *, user_id, access="write", workspace="/approved"):
    item = MCPGrantModel(requester=f"user:{user_id}", server="lensword", tool=tool, access=access, workspace=workspace, mode="always")
    db_session.add(item)
    db_session.flush()
    return item


def _invoke(client, headers, tool, payload, *, workspace="/approved"):
    payload = dict(payload)
    if "request_id" not in payload and tool not in ("lensword.get_companion_session", "lensword.get_companion_task"):
        payload["request_id"] = str(uuid.uuid4())
    return client.post("/api/v1/mcp/invoke", headers=headers, json={"workspace": workspace, "tool": tool, "payload": payload})


def test_a_second_account_cannot_read_or_transition_anothers_companion_session_via_mcp(client, auth_headers, db_session):
    alice = auth_headers(username="mcp-idor-alice", email="mcp-idor-alice@example.com")
    bob = auth_headers(username="mcp-idor-bob", email="mcp-idor-bob@example.com")
    _enable_companion(client, alice)
    _enable_companion(client, bob)
    alice_id, bob_id = _user_id(client, alice), _user_id(client, bob)

    _grant(db_session, "lensword.start_companion_session", user_id=alice_id)
    started = _invoke(client, alice, "lensword.start_companion_session", {"connection_id": "alice-conn", "client_id": "alice-host"})
    assert started.status_code == 200, started.text
    alice_session_id = started.json()["id"]

    # Bob holds real, valid grants for every tool below — for his own
    # account. The only thing he supplies that isn't his is Alice's real
    # session id (guessed, or observed some other way — the point is he
    # never started this session himself).
    for tool, access in (
        ("lensword.get_companion_session", "read"),
        ("lensword.resume_companion_session", "write"),
        ("lensword.pause_companion_session", "write"),
        ("lensword.finish_companion_session", "write"),
    ):
        _grant(db_session, tool, access=access, user_id=bob_id)

    get_response = _invoke(client, bob, "lensword.get_companion_session", {"session_id": alice_session_id})
    assert get_response.status_code == 400, get_response.text
    assert "not found" in get_response.json()["detail"].lower()

    for tool in ("lensword.resume_companion_session", "lensword.pause_companion_session", "lensword.finish_companion_session"):
        response = _invoke(client, bob, tool, {"session_id": alice_session_id})
        assert response.status_code == 400, f"{tool}: {response.text}"
        assert "not found" in response.json()["detail"].lower()

    # Alice's session is untouched — still readable, and still in the state
    # she left it in, not paused/finished by Bob's denied attempts.
    _grant(db_session, "lensword.get_companion_session", access="read", user_id=alice_id)
    still_alices = _invoke(client, alice, "lensword.get_companion_session", {"session_id": alice_session_id})
    assert still_alices.status_code == 200
    assert still_alices.json()["status"] == "active"


def test_a_second_account_cannot_read_or_cancel_anothers_companion_task_via_mcp(client, auth_headers, db_session):
    alice = auth_headers(username="mcp-idor-task-alice", email="mcp-idor-task-alice@example.com")
    bob = auth_headers(username="mcp-idor-task-bob", email="mcp-idor-task-bob@example.com")
    _enable_companion(client, alice)
    _enable_companion(client, bob)
    alice_id, bob_id = _user_id(client, alice), _user_id(client, bob)

    _grant(db_session, "lensword.start_companion_session", user_id=alice_id)
    session = _invoke(client, alice, "lensword.start_companion_session", {"connection_id": "alice-conn", "client_id": "alice-host"})
    assert session.status_code == 200, session.text
    alice_session_id = session.json()["id"]

    _grant(db_session, "lensword.start_extraction_task", user_id=alice_id)
    task = _invoke(
        client, alice, "lensword.start_extraction_task",
        {"companion_session_id": alice_session_id, "text": "hola mundo", "target_language": "es"},
    )
    assert task.status_code == 200, task.text
    alice_task_id = task.json()["id"]

    # Bob has real grants for the read/cancel task tools, and even knows
    # Alice's session id (e.g. leaked through an earlier legitimate
    # interaction) — but never started this task himself.
    _grant(db_session, "lensword.get_companion_task", access="read", user_id=bob_id)
    _grant(db_session, "lensword.cancel_companion_task", access="write", user_id=bob_id)

    get_response = _invoke(
        client, bob, "lensword.get_companion_task", {"companion_session_id": alice_session_id, "task_id": alice_task_id},
    )
    assert get_response.status_code == 400, get_response.text

    cancel_response = _invoke(
        client, bob, "lensword.cancel_companion_task", {"companion_session_id": alice_session_id, "task_id": alice_task_id},
    )
    assert cancel_response.status_code == 400, cancel_response.text

    # Alice's task is still there, unaffected by Bob's denied cancel.
    _grant(db_session, "lensword.get_companion_task", access="read", user_id=alice_id)
    still_alices = _invoke(
        client, alice, "lensword.get_companion_task", {"companion_session_id": alice_session_id, "task_id": alice_task_id},
    )
    assert still_alices.status_code == 200
    assert still_alices.json()["status"] != "cancelled"
