"""Use cases behind the MCP-facing companion task tools (#197 TODO 2).

These wrap the existing `companion_tasks.py` domain state machine and the
`companion_task_execution.py` pure helpers — nothing here duplicates that
logic. `mcp.py`'s bindings and the existing REST router
(`api/routers/companion_tasks.py`) are both thin transports over the same
state; a task created through either surface is visible and progresses
identically through the other, because both read and write the same
`CompanionTaskRepository`.
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
    WordRepository,
)
from app.domain.services.companion_sessions import CompanionSessionStatus
from app.domain.services.companion_task_execution import DueWordRef, extract_candidate_terms, plan_micro_session_units
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


class CreatePlanGenerationTaskUseCase:
    """Create a durable task that builds a bounded micro-session plan.

    Each unit creates one real, measurable `LearningActivity` (#194) bound to
    the session — this is not a preview or a dry run, the activities exist
    the moment their unit runs.
    """

    def __init__(
        self,
        task_repo: CompanionTaskRepository,
        session_repo: CompanionSessionRepository,
        settings_repo: RecallSettingsRepository,
        word_repo: WordRepository,
    ):
        self.task_repo = task_repo
        self.session_repo = session_repo
        self.settings_repo = settings_repo
        self.word_repo = word_repo

    def execute(
        self,
        user_id: int,
        session_id: str,
        size: int = 5,
        operation_id: str | None = None,
    ) -> CompanionTask:
        _require_companion_enabled(self.settings_repo, user_id)
        session = _require_active_session(self.session_repo, user_id, session_id)
        if operation_id:
            existing = self.task_repo.find_by_operation(user_id, session_id, operation_id)
            if existing is not None:
                return existing
        due_words = [
            DueWordRef(word_id=word.id, term=word.term)
            for word in self.word_repo.list_due_for_user(user_id, max(size, 1), session.group_id)
            if word.id is not None
        ]
        selected = plan_micro_session_units(due_words, size)
        if not selected:
            raise ValidationError("no due words are available to plan a micro-session from")
        now = utcnow()
        return self.task_repo.add(
            CompanionTask(
                id=uuid4().hex,
                session_id=session_id,
                user_id=user_id,
                task_type=CompanionTaskType.PLAN_GENERATION,
                status=CompanionTaskStatus.PENDING,
                total_units=len(selected),
                completed_units=0,
                result=None,
                error=None,
                operation_id=operation_id,
                expires_at=now + timedelta(seconds=DEFAULT_TASK_TTL_SECONDS),
                created_at=now,
                updated_at=now,
                input={"items": [{"word_id": ref.word_id, "term": ref.term} for ref in selected]},
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
