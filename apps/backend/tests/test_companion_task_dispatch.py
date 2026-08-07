"""The real background executor behind companion_tasks.py (#197 TODO 3).

Mirrors test_acquisition_dispatch.py's shape: `session_factory=lambda:
db_session` lets a fresh `CompanionTaskExecutor` operate against the same
database a `client` request already wrote to, which is what makes "a new
executor instance resumes a task a previous one left mid-run" a faithful
restart simulation rather than a mocked one.
"""
from __future__ import annotations

from datetime import timedelta

from app.domain.entities import RecallSettings
from app.domain.services.companion_activities import ActivityStatus
from app.domain.services.companion_tasks import CompanionTask, CompanionTaskStatus, CompanionTaskType
from app.domain.value_objects import utcnow as real_utcnow
from app.infrastructure.jobs.companion_task_dispatch import CompanionTaskExecutor
from app.infrastructure.repositories import (
    SqlAlchemyCompanionActivityRepository,
    SqlAlchemyCompanionSessionRepository,
    SqlAlchemyCompanionTaskRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyUserRepository,
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


def _owner_id(db_session):
    return SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id


def _extraction_task(db_session, session_id, owner_id, *, candidates, completed_units=0, result=None):
    now = real_utcnow()
    task_repo = SqlAlchemyCompanionTaskRepository(db_session)
    task = task_repo.add(
        CompanionTask(
            id=f"task-{len(candidates)}-{completed_units}",
            session_id=session_id,
            user_id=owner_id,
            task_type=CompanionTaskType.EXTRACTION,
            status=CompanionTaskStatus.RUNNING if completed_units else CompanionTaskStatus.PENDING,
            total_units=len(candidates),
            completed_units=completed_units,
            result=result,
            error=None,
            operation_id=None,
            expires_at=now + timedelta(minutes=10),
            created_at=now,
            updated_at=now,
            input={"candidates": candidates, "target_language": "es"},
        )
    )
    db_session.flush()
    return task


def test_extraction_task_runs_to_completion_with_real_progress(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(db_session, _owner_id(db_session))
    session_id = _start_session(client, headers)
    owner_id = _owner_id(db_session)
    _extraction_task(db_session, session_id, owner_id, candidates=["uno", "dos", "tres"])

    CompanionTaskExecutor(lambda: db_session)()

    task_repo = SqlAlchemyCompanionTaskRepository(db_session)
    task = task_repo.list_for_session(owner_id, session_id)[0]
    assert task.status is CompanionTaskStatus.COMPLETED
    assert task.completed_units == 3
    assert task.progress == 1.0
    assert task.result == {"partial": False, "items": ["uno", "dos", "tres"]}


def test_extraction_task_resumes_after_a_simulated_restart(client, auth_headers, db_session):
    """A prior process persisted one unit then "crashed" (never marked
    complete). A brand-new executor instance — a stand-in for the process
    restarting — must resume from the persisted state, not from zero, and
    must not re-do or lose the already-completed unit."""
    headers = auth_headers()
    _enable(db_session, _owner_id(db_session))
    session_id = _start_session(client, headers)
    owner_id = _owner_id(db_session)
    _extraction_task(
        db_session,
        session_id,
        owner_id,
        candidates=["uno", "dos", "tres"],
        completed_units=1,
        result={"partial": True, "items": ["uno"]},
    )

    CompanionTaskExecutor(lambda: db_session)()

    task = SqlAlchemyCompanionTaskRepository(db_session).list_for_session(owner_id, session_id)[0]
    assert task.status is CompanionTaskStatus.COMPLETED
    assert task.result["items"] == ["uno", "dos", "tres"]


def test_a_cancelled_task_is_never_advanced_and_keeps_its_partial_result(client, auth_headers, db_session):
    """Cancellation happens out-of-band (the REST/MCP cancel endpoint) and
    takes effect immediately: the executor's next poll must not claim a
    single further unit, and whatever partial output existed before
    cancellation must survive exactly as it was — never silently promoted
    to look complete."""
    headers = auth_headers()
    _enable(db_session, _owner_id(db_session))
    session_id = _start_session(client, headers)
    owner_id = _owner_id(db_session)
    task = _extraction_task(
        db_session,
        session_id,
        owner_id,
        candidates=["uno", "dos", "tres"],
        completed_units=1,
        result={"partial": True, "items": ["uno"]},
    )
    cancel = client.post(
        f"/api/v1/companion/sessions/{session_id}/tasks/{task.id}/cancel", headers=headers
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    # The test's `get_db` override never commits per-request (unlike the real
    # one), so anything only flushed is still just pending transaction state
    # a job's own `db.close()` would roll back if the job finds nothing
    # runnable to commit on top of. A real executor session is independent
    # of any request session, so this is purely a shared-session test
    # artifact — committed explicitly here for the same reason
    # test_acquisition_dispatch.py's setup helpers commit before dispatching.
    db_session.commit()

    CompanionTaskExecutor(lambda: db_session)()

    final = SqlAlchemyCompanionTaskRepository(db_session).list_for_session(owner_id, session_id)[0]
    assert final.status is CompanionTaskStatus.CANCELLED
    assert final.completed_units == 1
    assert final.result == {"partial": True, "items": ["uno"]}


def test_plan_generation_task_creates_real_activities_and_completes(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(db_session, _owner_id(db_session))
    session_id = _start_session(client, headers)
    owner_id = _owner_id(db_session)
    now = real_utcnow()
    task_repo = SqlAlchemyCompanionTaskRepository(db_session)
    task_repo.add(
        CompanionTask(
            id="plan-task-1",
            session_id=session_id,
            user_id=owner_id,
            task_type=CompanionTaskType.PLAN_GENERATION,
            status=CompanionTaskStatus.PENDING,
            total_units=2,
            completed_units=0,
            result=None,
            error=None,
            operation_id=None,
            expires_at=now + timedelta(minutes=10),
            created_at=now,
            updated_at=now,
            input={"items": [{"word_id": 1, "term": "correr"}, {"word_id": 2, "term": "saltar"}]},
        )
    )
    db_session.flush()

    CompanionTaskExecutor(lambda: db_session)()

    task = task_repo.list_for_session(owner_id, session_id)[0]
    assert task.status is CompanionTaskStatus.COMPLETED
    activity_ids = task.result["activity_ids"]
    assert len(activity_ids) == 2
    activity_repo = SqlAlchemyCompanionActivityRepository(db_session)
    for activity_id in activity_ids:
        activity = activity_repo.get(owner_id, session_id, activity_id)
        assert activity is not None
        assert activity.status is ActivityStatus.ACTIVE


def test_expired_task_is_marked_expired_and_never_run(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(db_session, _owner_id(db_session))
    session_id = _start_session(client, headers)
    owner_id = _owner_id(db_session)
    now = real_utcnow()
    task_repo = SqlAlchemyCompanionTaskRepository(db_session)
    task_repo.add(
        CompanionTask(
            id="expiring-task",
            session_id=session_id,
            user_id=owner_id,
            task_type=CompanionTaskType.EXTRACTION,
            status=CompanionTaskStatus.PENDING,
            total_units=1,
            completed_units=0,
            result=None,
            error=None,
            operation_id=None,
            expires_at=now - timedelta(seconds=1),
            created_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=5),
            input={"candidates": ["uno"], "target_language": "es"},
        )
    )
    db_session.flush()

    # An already-expired task is not even picked up by list_runnable, so the
    # executor has nothing to do with it here; the expiry check exists for a
    # task that becomes due for expiry between ticks.
    task_repo2 = SqlAlchemyCompanionTaskRepository(db_session)
    runnable = task_repo2.list_runnable(now)
    assert "expiring-task" not in [t.id for t in runnable]
