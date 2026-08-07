"""Application-layer orchestration for bounded companion session planning
(#194 TODO 4) — the I/O half of `app.domain.services.companion_planning`,
which stays pure. Generating a plan never writes an activity; only
`ConfirmCompanionActivityPlanUseCase`, and only when explicitly told the
plan is confirmed, does.
"""
from __future__ import annotations

import uuid

from app.application.use_cases.companion_activities import BeginLearningActivityUseCase
from app.application.use_cases.conversation_context import AssembleConversationContextUseCase
from app.domain.exceptions import ValidationError
from app.domain.repositories import CompanionActivityRepository
from app.domain.services.companion_activities import ActivityStatus, LearningActivity
from app.domain.services.companion_planning import ActivityPlan, generate_activity_plan
from app.domain.value_objects import utcnow


class GenerateCompanionActivityPlanUseCase:
    """Assembles the same bounded facts a companion session itself would
    see (#194 TODO 2) and turns them into a bounded, unconfirmed plan (#194
    TODO 4). Read-only: nothing here writes an activity or a task."""

    def __init__(self, context_use_case: AssembleConversationContextUseCase):
        self.context_use_case = context_use_case

    def execute(self, user_id: int, session_id: str, *, max_activities: int = 5) -> ActivityPlan:
        context = self.context_use_case.execute(user_id, session_id)
        return generate_activity_plan(context, max_activities=max_activities)


class ConfirmCompanionActivityPlanUseCase:
    """Executes a plan — actually creating the `LearningActivity` rows it
    proposes, the only step that can lead to a write observation — behind
    an explicit `confirmed=True` from the caller (#194 TODO 4). Mirrors the
    `PlanExecuteRequest.confirmed` gate `app.api.routers.mcp_plans` already
    uses for MCP command plans: nothing here writes anything until a caller
    has said so out loud, and a plan already confirmed once
    (`CompanionTask.record_plan_confirmation`) cannot be executed again.
    """

    def __init__(self, activity_repo: CompanionActivityRepository, begin_activity: BeginLearningActivityUseCase):
        self.activity_repo = activity_repo
        self.begin_activity = begin_activity

    def execute(self, user_id: int, plan: ActivityPlan, *, confirmed: bool) -> list[LearningActivity]:
        if not confirmed:
            raise ValidationError("Executing a companion activity plan requires explicit confirmation")

        created: list[LearningActivity] = []
        now = utcnow()
        for item in plan.items:
            expected_evaluation = {"word_id": item.word_id}
            self.begin_activity.validate(user_id, item.activity_type, expected_evaluation)

            operation_id = f"plan:{plan.session_id}:{item.word_id}:{item.activity_type.value}"
            existing = self.activity_repo.find_by_operation(user_id, plan.session_id, operation_id)
            if existing is not None:
                created.append(existing)
                continue

            activity = self.activity_repo.add(
                LearningActivity(
                    id=uuid.uuid4().hex,
                    session_id=plan.session_id,
                    user_id=user_id,
                    activity_type=item.activity_type,
                    prompt=f"Practice '{item.term}': {item.rationale}"[:4000],
                    expected_evaluation=expected_evaluation,
                    status=ActivityStatus.ACTIVE,
                    response=None,
                    result=None,
                    operation_id=operation_id,
                    started_at=now,
                    updated_at=now,
                )
            )
            created.append(activity)
        return created
