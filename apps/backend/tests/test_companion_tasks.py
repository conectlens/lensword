from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.companion_tasks import (
    CompanionTask,
    CompanionTaskStatus,
    CompanionTaskType,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task(**overrides):
    values = {
        "id": "task-1",
        "session_id": "session-1",
        "user_id": 1,
        "task_type": CompanionTaskType.EXTRACTION,
        "status": CompanionTaskStatus.PENDING,
        "total_units": 4,
        "completed_units": 0,
        "result": None,
        "error": None,
        "operation_id": "op-1",
        "expires_at": NOW + timedelta(minutes=5),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return CompanionTask(**values)


def test_task_progress_is_explicit_monotonic_and_completes_at_total():
    task = _task()
    task.update_progress(2, NOW + timedelta(seconds=1))
    assert task.status is CompanionTaskStatus.RUNNING
    assert task.progress == 0.5
    with pytest.raises(ValueError, match="backwards"):
        task.update_progress(1, NOW + timedelta(seconds=2))
    task.complete({"items": 2}, NOW + timedelta(seconds=3))
    assert task.status is CompanionTaskStatus.COMPLETED
    assert task.completed_units == 4
    assert task.progress == 1.0


def test_task_cancellation_is_idempotent_but_terminal_state_is_not_reopened():
    task = _task()
    task.cancel(NOW + timedelta(seconds=1))
    task.cancel(NOW + timedelta(seconds=2))
    assert task.status is CompanionTaskStatus.CANCELLED
    with pytest.raises(ValueError, match="terminal"):
        task.start(NOW + timedelta(seconds=3))


def test_task_expiration_is_a_persisted_terminal_state():
    task = _task(expires_at=NOW + timedelta(seconds=1))
    assert task.expire_if_due(NOW + timedelta(seconds=1)) is True
    assert task.status is CompanionTaskStatus.EXPIRED
    assert task.expire_if_due(NOW + timedelta(seconds=2)) is False


def test_task_rejects_unbounded_work():
    with pytest.raises(ValueError, match="10000"):
        _task(total_units=10001)


def _enable(client, headers):
    response = client.put(
        "/api/v1/recall-settings",
        json={"ai_companion_enabled": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _start_session(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_task_api_is_owner_scoped_idempotent_and_cancellable(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)
    created = client.post(
        f"/api/v1/companion/sessions/{session_id}/tasks",
        json={"task_type": "extraction", "total_units": 3, "operation_id": "task-op"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "pending"
    assert task["progress"] == 0

    duplicate = client.post(
        f"/api/v1/companion/sessions/{session_id}/tasks",
        json={"task_type": "extraction", "total_units": 99, "operation_id": "task-op"},
        headers=headers,
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == task["id"]
    assert duplicate.json()["total_units"] == 3

    progress = client.post(
        f"/api/v1/companion/sessions/{session_id}/tasks/{task['id']}/progress",
        json={"completed_units": 2},
        headers=headers,
    )
    assert progress.status_code == 200
    assert progress.json()["status"] == "running"
    assert progress.json()["progress"] == pytest.approx(2 / 3)

    cancelled = client.post(
        f"/api/v1/companion/sessions/{session_id}/tasks/{task['id']}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
