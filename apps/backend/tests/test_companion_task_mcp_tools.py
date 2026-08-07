"""MCP tool contracts wrapping the companion_tasks domain model (#197 TODO 2).

Follows test_mcp_security.py's shape for granting and invoking a tool over
the real `/api/v1/mcp/invoke` boundary — policy, audit, and idempotency all
apply to these tools exactly as they do to every other one, because they go
through the same MCPDispatcher/MCPPolicyGate, not a parallel path.
"""
from __future__ import annotations

from app.domain.entities import RecallSettings
from app.infrastructure.jobs.companion_task_dispatch import CompanionTaskExecutor
from app.infrastructure.models import MCPGrantModel
from app.infrastructure.repositories import (
    SqlAlchemyCompanionTaskRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyUserRepository,
)

# `is_valid_workspace` in app/api/routers/mcp.py deliberately checks
# `PurePosixPath(...).is_absolute()` rather than the platform-dependent
# `pathlib.PurePath` (a real bug that fix closed) — every workspace string
# in this codebase is POSIX-style, matching test_mcp_security.py's own
# "/approved" convention, and that is true on every host this now runs on.
_WORKSPACE = "/approved"


def _owner_id(db_session):
    return SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id


def _requester(owner_id):
    # Caller identity for a login-JWT-authenticated /invoke call is derived
    # server-side by `MCPActor.for_login` (app/api/mcp_auth.py, issue #196
    # TODO 2) as `f"user:{user.id}"` — never a caller-supplied string, which
    # is exactly the deputy-attack surface that fix closed. Grants must be
    # written against that same derived identity to ever match.
    return f"user:{owner_id}"


def _grant(db_session, *, owner_id, tool, access):
    item = MCPGrantModel(
        requester=_requester(owner_id), server="lensword", tool=tool, access=access,
        workspace=_WORKSPACE, mode="always",
    )
    db_session.add(item)
    db_session.flush()
    return item


def _invoke(client, headers, *, tool, payload):
    return client.post(
        "/api/v1/mcp/invoke",
        headers=headers,
        json={"workspace": _WORKSPACE, "tool": tool, "payload": payload},
    )


def _enable(db_session, user_id):
    repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings = repo.get_by_user(user_id) or RecallSettings(user_id=user_id)
    settings.ai_companion_enabled = True
    repo.upsert(settings)
    db_session.flush()


def _start_session(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_start_extraction_task_creates_a_durable_task_the_executor_can_finish(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(db_session)
    _enable(db_session, owner_id)
    session_id = _start_session(client, headers)
    _grant(db_session, owner_id=owner_id, tool="lensword.start_extraction_task", access="write")

    response = _invoke(
        client,
        headers,
        tool="lensword.start_extraction_task",
        payload={
            "companion_session_id": session_id,
            "text": "The cat sat on the mat",
            "target_language": "es",
            "max_terms": 10,
            "request_id": "req-create",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["completed_units"] == 0
    assert body["total_units"] > 0

    CompanionTaskExecutor(lambda: db_session)()
    task = SqlAlchemyCompanionTaskRepository(db_session).get(owner_id, session_id, body["id"])
    assert task.status.value == "completed"
    assert task.progress == 1.0


def test_start_extraction_task_is_idempotent_on_request_id(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(db_session)
    _enable(db_session, owner_id)
    session_id = _start_session(client, headers)
    _grant(db_session, owner_id=owner_id, tool="lensword.start_extraction_task", access="write")

    payload = {
        "companion_session_id": session_id,
        "text": "hola mundo",
        "target_language": "es",
        "request_id": "req-1",
    }
    first = _invoke(client, headers, tool="lensword.start_extraction_task", payload=payload)
    second = _invoke(client, headers, tool="lensword.start_extraction_task", payload=payload)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    tasks = SqlAlchemyCompanionTaskRepository(db_session).list_for_session(owner_id, session_id)
    assert len(tasks) == 1


def test_get_and_cancel_companion_task_tools_wrap_the_same_state(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(db_session)
    _enable(db_session, owner_id)
    session_id = _start_session(client, headers)
    _grant(db_session, owner_id=owner_id, tool="lensword.start_extraction_task", access="write")
    _grant(db_session, owner_id=owner_id, tool="lensword.get_companion_task", access="read")
    _grant(db_session, owner_id=owner_id, tool="lensword.cancel_companion_task", access="write")

    created = _invoke(
        client,
        headers,
        tool="lensword.start_extraction_task",
        payload={
            "companion_session_id": session_id,
            "text": "hola mundo amigo",
            "target_language": "es",
            "request_id": "req-create",
        },
    ).json()
    assert "id" in created, created

    fetched = _invoke(
        client,
        headers,
        tool="lensword.get_companion_task",
        payload={"companion_session_id": session_id, "task_id": created["id"]},
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]

    cancelled = _invoke(
        client,
        headers,
        tool="lensword.cancel_companion_task",
        payload={"companion_session_id": session_id, "task_id": created["id"], "request_id": "req-cancel"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # And the REST surface (existing #197 router) sees the same row.
    via_rest = client.get(
        f"/api/v1/companion/sessions/{session_id}/tasks/{created['id']}", headers=headers
    )
    assert via_rest.json()["status"] == "cancelled"


def test_companion_task_tools_are_refused_without_ai_companion_enabled(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = _owner_id(db_session)
    _enable(db_session, owner_id)
    session_id = _start_session(client, headers)
    _grant(db_session, owner_id=owner_id, tool="lensword.start_extraction_task", access="write")

    # Turned back off after the session already exists: the task tool must
    # re-check the flag itself rather than trust that an active session
    # implies it is still on.
    settings_repo = SqlAlchemyRecallSettingsRepository(db_session)
    settings = settings_repo.get_by_user(owner_id)
    settings.ai_companion_enabled = False
    settings_repo.upsert(settings)
    db_session.flush()

    response = _invoke(
        client,
        headers,
        tool="lensword.start_extraction_task",
        payload={
            "companion_session_id": session_id,
            "text": "hola",
            "target_language": "es",
            "request_id": "req-disabled",
        },
    )
    assert response.status_code == 400
