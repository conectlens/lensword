"""Use cases behind the MCP-facing companion task tools (#197 TODO 2).

These wrap the existing `companion_tasks.py` domain state machine and the
`companion_task_execution.py` pure helpers — nothing here duplicates that
logic. `mcp.py`'s bindings and the existing REST router
(`api/routers/companion_tasks.py`) are both thin transports over the same
state; a task created through either surface is visible and progresses
identically through the other, because both read and write the same
`CompanionTaskRepository`.

Only extraction task creation lives here — not plan generation. #194 TODO 4
already gave `plan_generation` tasks a real, synchronous, context-aware
lifecycle (`GenerateCompanionActivityPlanUseCase`/
`ConfirmCompanionActivityPlanUseCase`, wired through
`app.api.routers.companion_tasks`'s `generate-plan`/`confirm-plan`
endpoints), discovered while rebasing this change onto `development`. A
second `plan_generation`-creating use case here would just be a competing,
less capable implementation of something that already exists — see
`app.infrastructure.jobs.companion_task_dispatch`'s module docstring for
the same reasoning on the executor side.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.domain.entities import RecallSettings
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError, ValidationError
from app.domain.repositories import (
    CompanionSessionRepository,
    CompanionTaskRepository,
    RecallSettingsRepository,
)
from app.domain.services.companion_sessions import CompanionSessionStatus
from app.domain.services.companion_task_execution import extract_candidate_terms
from app.domain.services.companion_tasks import CompanionTask, CompanionTaskStatus, CompanionTaskType
from app.domain.value_objects import utcnow

DEFAULT_TASK_TTL_SECONDS = 600


def _require_companion_enabled(settings_repo: RecallSettingsRepository, user_id: int) -> None:
    settings = settings_repo.get_by_user(user_id)
    if not settings or not settings.ai_companion_enabled:
        raise PermissionDeniedError("AI Companion is not enabled")


def _require_active_session(session_repo: CompanionSessionRepository, user_id: int, session_id: str):
    session = session_repo.get(user_id, session_id)
    if session is None:
        raise EntityNotFoundError("CompanionSession", session_id)
    if session.status is not CompanionSessionStatus.ACTIVE:
        raise PermissionDeniedError("Companion session is not active")
    return session


class CreateExtractionTaskUseCase:
    """Create a durable, cancellable, resumable extraction task.

    Candidates are computed once, deterministically, at creation time (not
    re-derived by the executor mid-run) so `total_units` is exact and the
    executor never has to re-tokenize — see `companion_task_dispatch.py`.
    """

    def __init__(
        self,
        task_repo: CompanionTaskRepository,
        session_repo: CompanionSessionRepository,
        settings_repo: RecallSettingsRepository,
    ):
        self.task_repo = task_repo
        self.session_repo = session_repo
        self.settings_repo = settings_repo

    def execute(
        self,
        user_id: int,
        session_id: str,
        text: str,
        target_language: str,
        max_terms: int = 20,
        operation_id: str | None = None,
    ) -> CompanionTask:
        _require_companion_enabled(self.settings_repo, user_id)
        _require_active_session(self.session_repo, user_id, session_id)
        if operation_id:
            existing = self.task_repo.find_by_operation(user_id, session_id, operation_id)
            if existing is not None:
                return existing
        candidates = extract_candidate_terms(text, max_terms)
        if not candidates:
            raise ValidationError("no extractable candidate terms were found in the supplied text")
        now = utcnow()
        return self.task_repo.add(
            CompanionTask(
                id=uuid4().hex,
                session_id=session_id,
                user_id=user_id,
                task_type=CompanionTaskType.EXTRACTION,
                status=CompanionTaskStatus.PENDING,
                total_units=len(candidates),
                completed_units=0,
                result=None,
                error=None,
                operation_id=operation_id,
                expires_at=now + timedelta(seconds=DEFAULT_TASK_TTL_SECONDS),
                created_at=now,
                updated_at=now,
                input={"candidates": candidates, "target_language": target_language},
            )
        )


class GetCompanionTaskUseCase:
    def __init__(
        self,
        task_repo: CompanionTaskRepository,
        session_repo: CompanionSessionRepository,
        settings_repo: RecallSettingsRepository,
    ):
        self.task_repo = task_repo
        self.session_repo = session_repo
        self.settings_repo = settings_repo

    def execute(self, user_id: int, session_id: str, task_id: str) -> CompanionTask:
        _require_companion_enabled(self.settings_repo, user_id)
        _require_active_session(self.session_repo, user_id, session_id)
        task = self.task_repo.get(user_id, session_id, task_id)
        if task is None:
            raise EntityNotFoundError("CompanionTask", task_id)
        if task.expire_if_due(utcnow()):
            task = self.task_repo.update(task)
        return task


class CancelCompanionTaskUseCase:
    def __init__(
        self,
        task_repo: CompanionTaskRepository,
        session_repo: CompanionSessionRepository,
        settings_repo: RecallSettingsRepository,
    ):
        self.task_repo = task_repo
        self.session_repo = session_repo
        self.settings_repo = settings_repo

    def execute(self, user_id: int, session_id: str, task_id: str) -> CompanionTask:
        _require_companion_enabled(self.settings_repo, user_id)
        _require_active_session(self.session_repo, user_id, session_id)
        task = self.task_repo.get(user_id, session_id, task_id)
        if task is None:
            raise EntityNotFoundError("CompanionTask", task_id)
        task.cancel(utcnow())
        return self.task_repo.update(task)
