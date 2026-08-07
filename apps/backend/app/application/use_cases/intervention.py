"""Learner-facing actions on an `InterventionPlan`, delayed-outcome
evaluation, and AI-generated content for a plan (issue #185 TODO 4/5,
issue #187 TODO 2).

`RunDiagnosisForWordUseCase` (diagnosis.py) creates plans; everything here
acts on a plan that already exists — reject/postpone/choose an alternative
(TODO 4's "let users reject, postpone, or choose an alternative"), list the
ones still awaiting a learner decision, mark a plan's delayed effectiveness
once enough evidence exists (TODO 5), and — `ExplainInterventionUseCase`,
below — generate bounded, evidence-grounded content for one (#187 TODO 2).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.exceptions import AIProviderUnavailableError, EntityNotFoundError, PermissionDeniedError, ValidationError
from app.domain.repositories import DiagnosisRepository, InterventionRepository, LearningObservationRepository
from app.domain.services.ai_provider import AIProvider
from app.domain.services.companion_coach import (
    CoachContent,
    CoachContentRejected,
    CoachRequest,
    build_coach_request,
    deterministic_fallback,
)
from app.domain.services.diagnosis_contracts import InterventionOutcome, InterventionPlan
from app.domain.services.intervention_planning import InterventionStrategy, evaluate_intervention_outcome
from app.domain.value_objects import ReviewOutcome, utcnow

# TODO 5: the wall-clock checkpoints, evaluated against a plan's `planned_at`
# in addition to the "next_review" checkpoint below. "immediate" is not a
# member here — it belongs to TODO 4's completion outcomes
# (resolved/abandoned/rejected/postponed), recorded synchronously by the
# actions in this module, not computed from a delayed observation window.
_TIME_HORIZONS: tuple[tuple[str, timedelta], ...] = (
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
)

_TERMINAL_RESULTS = frozenset({"resolved", "abandoned", "rejected"})


def active_plans(plans: list[InterventionPlan], outcomes: list[InterventionOutcome]) -> list[InterventionPlan]:
    """A plan is still active until a TODO 4 completion outcome has been
    recorded for it — the same "active" test `is_duplicate_of_active_plan`
    uses, applied here so a resolved/abandoned/rejected plan does not keep
    showing up as something to decide on."""
    closed_strategies = {o.strategy for o in outcomes if o.result in _TERMINAL_RESULTS}
    return [p for p in plans if p.strategy not in closed_strategies]


def _get_owned_plan(intervention_repo: InterventionRepository, user_id: int, plan_id: int) -> InterventionPlan:
    plan = intervention_repo.get_plan(user_id, plan_id)
    if plan is None:
        raise EntityNotFoundError("InterventionPlan", plan_id)
    return plan


class ListActiveInterventionPlansUseCase:
    def __init__(self, intervention_repo: InterventionRepository):
        self.intervention_repo = intervention_repo

    def execute(self, user_id: int, word_id: int) -> list[InterventionPlan]:
        plans = self.intervention_repo.list_plans_for_word(user_id, word_id)
        outcomes = self.intervention_repo.list_outcomes_for_word(user_id, word_id)
        return active_plans(plans, outcomes)


class RejectInterventionPlanUseCase:
    def __init__(self, intervention_repo: InterventionRepository):
        self.intervention_repo = intervention_repo

    def execute(self, user_id: int, plan_id: int, *, now: datetime | None = None) -> InterventionOutcome:
        plan = _get_owned_plan(self.intervention_repo, user_id, plan_id)
        return self.intervention_repo.add_outcome(
            InterventionOutcome(
                word_id=plan.word_id, user_id=user_id, strategy=plan.strategy,
                completed=False, result="rejected", recorded_at=now or utcnow(),
            )
        )


class PostponeInterventionPlanUseCase:
    def __init__(self, intervention_repo: InterventionRepository):
        self.intervention_repo = intervention_repo

    def execute(self, user_id: int, plan_id: int, *, now: datetime | None = None) -> InterventionOutcome:
        plan = _get_owned_plan(self.intervention_repo, user_id, plan_id)
        # Deliberately not in _TERMINAL_RESULTS: postponing keeps the plan
        # active (TODO 4 draws "reject" and "postpone" as different learner
        # choices — one is a completion, the other is a snooze).
        return self.intervention_repo.add_outcome(
            InterventionOutcome(
                word_id=plan.word_id, user_id=user_id, strategy=plan.strategy,
                completed=False, result="postponed", recorded_at=now or utcnow(),
            )
        )


class ChooseAlternativeInterventionUseCase:
    """TODO 4: "let users ... choose an alternative." The original plan is
    closed as abandoned — a new fact, not an edit — and a new plan is
    created for the strategy the learner picked, mirroring how
    `plan_intervention` itself never mutates a plan in place."""

    def __init__(self, intervention_repo: InterventionRepository):
        self.intervention_repo = intervention_repo

    def execute(
        self, user_id: int, plan_id: int, alternative_strategy: str, *, now: datetime | None = None
    ) -> InterventionPlan:
        if alternative_strategy not in {s.value for s in InterventionStrategy}:
            raise ValidationError(f"Unknown intervention strategy: {alternative_strategy}")

        plan = _get_owned_plan(self.intervention_repo, user_id, plan_id)
        moment = now or utcnow()
        self.intervention_repo.add_outcome(
            InterventionOutcome(
                word_id=plan.word_id, user_id=user_id, strategy=plan.strategy,
                completed=False, result="abandoned", recorded_at=moment,
            )
        )
        return self.intervention_repo.add_plan(
            InterventionPlan(
                word_id=plan.word_id, user_id=user_id, diagnosis_outcome=plan.diagnosis_outcome,
                strategy=alternative_strategy, policy_version=plan.policy_version, eligible=True,
                rationale="Learner-chosen alternative to the original plan.", planned_at=moment,
                second_word_id=plan.second_word_id, prerequisite_ids=plan.prerequisite_ids,
            )
        )


class EvaluateInterventionOutcomesUseCase:
    """TODO 5: mark a plan effective/ineffective/inconclusive at the
    immediate/24h/7d/next-review checkpoints, from delayed evidence —
    called opportunistically whenever a word is re-diagnosed
    (`RunDiagnosisForWordUseCase`), the same "no dedicated background job in
    this pass" pragmatism `test_intervention_persistence.py` already
    documents for reads.
    """

    def __init__(self, intervention_repo: InterventionRepository, observation_repo: LearningObservationRepository):
        self.intervention_repo = intervention_repo
        self.observation_repo = observation_repo

    def execute(self, user_id: int, word_id: int, *, now: datetime | None = None) -> list[InterventionOutcome]:
        moment = now or utcnow()
        plans = self.intervention_repo.list_plans_for_word(user_id, word_id)
        if not plans:
            return []

        outcomes = self.intervention_repo.list_outcomes_for_word(user_id, word_id)
        observations = self.observation_repo.list_for_word(user_id, word_id)
        recorded: list[InterventionOutcome] = []

        for plan in active_plans(plans, outcomes):
            already_measured = {
                o.horizon for o in outcomes if o.strategy == plan.strategy and o.horizon != "immediate"
            }
            pre = [o for o in observations if o.observed_at < plan.planned_at]
            pre_correct = sum(1 for o in pre if o.outcome is ReviewOutcome.CORRECT)

            if "next_review" not in already_measured:
                post = [o for o in observations if o.observed_at >= plan.planned_at]
                if post:
                    recorded.append(
                        self._record(plan, moment, "next_review", pre_correct, len(pre), post)
                    )

            for horizon, delta in _TIME_HORIZONS:
                if horizon in already_measured or moment - plan.planned_at < delta:
                    continue
                post = [
                    o for o in observations
                    if plan.planned_at <= o.observed_at <= plan.planned_at + delta
                ]
                if post:
                    recorded.append(
                        self._record(plan, moment, horizon, pre_correct, len(pre), post)
                    )

        return recorded

    def _record(self, plan: InterventionPlan, moment: datetime, horizon: str, pre_correct: int, pre_total: int, post) -> InterventionOutcome:
        post_correct = sum(1 for o in post if o.outcome is ReviewOutcome.CORRECT)
        result = evaluate_intervention_outcome(
            pre_correct=pre_correct, pre_total=pre_total, post_correct=post_correct, post_total=len(post),
        )
        return self.intervention_repo.add_outcome(
            InterventionOutcome(
                word_id=plan.word_id, user_id=plan.user_id, strategy=plan.strategy,
                completed=True, result=result, recorded_at=moment, horizon=horizon,
            )
        )


# #187 TODO 2: which generated-content family a strategy gets. Only the
# strategies with a more specific generator are listed; everything else
# (ISOLATE, MORPHOLOGY_DECOMPOSITION, CONTEXT_VARIATION,
# PRODUCTION_PRACTICE, SPATIAL_ANCHOR, ACQUISITION_RESTART) falls through to
# the plain explanation below — a bounded, evidence-cited explanation is
# always a safe default even where no dedicated generator exists yet.
_CONTENT_TYPE_FOR_STRATEGY: dict[str, str] = {
    InterventionStrategy.CONTRAST.value: "contrast",
    InterventionStrategy.PREREQUISITE_PATH.value: "prerequisite",
    InterventionStrategy.MNEMONIC_REPLACEMENT.value: "mnemonic",
}


class ExplainInterventionUseCase:
    """AI-generated, evidence-grounded content for an existing
    `InterventionPlan` (issue #187 TODO 2).

    Nothing here is persisted onto the plan: `InterventionPlan` is one of
    this epic's append-only facts (see its docstring in
    diagnosis_contracts.py), and a generated explanation is a proposal the
    learner edits or rejects, not a new fact about the diagnosis — so this
    use case only ever reads the plan/diagnosis and returns content for the
    caller to hand back to the client.

    Split into a synchronous, database-bound half (`build_request`) and an
    awaitable half that touches no repository (`generate`), the same shape
    `SuggestMnemonicUseCase` (#185's own AI use case, review.py) already
    uses — so the router built on top can release its DB connection before
    the slow await (#187 TODO 5), the same way suggest_mnemonic's router
    does.
    """

    def __init__(self, diagnosis_repo: DiagnosisRepository, provider: AIProvider | None):
        self.diagnosis_repo = diagnosis_repo
        self.provider = provider

    def build_request(self, plan: InterventionPlan, target_language: str) -> CoachRequest:
        """The database-bound half: looks up the diagnosis that produced
        this plan (best-effort — build_coach_request falls back to the
        plan's own rationale when none matches) and shapes the bounded
        request. No provider call here."""
        diagnosis = self.diagnosis_repo.latest_for_word(plan.user_id, plan.word_id)
        content_type = _CONTENT_TYPE_FOR_STRATEGY.get(plan.strategy, "explanation")
        return build_coach_request(plan, diagnosis, target_language=target_language, content_type=content_type)

    async def generate(self, request: CoachRequest) -> tuple[str, CoachContent, str | None]:
        """The slow half. Touches no repository.

        Returns `(outcome, content, detail)` where `outcome` is one of
        "disabled"/"unavailable"/"rejected"/"ok" (#187 TODO 3's
        disabled-vs-unavailable-vs-ok pattern, extended with "rejected" for
        TODO 2's own "malformed/unsafe outputs rejected without losing the
        underlying plan"). Every branch except "ok" answers with
        `deterministic_fallback` so the caller always has content to show —
        never blocking on the AI the way TODO 5 requires.
        """
        if self.provider is None:
            return "disabled", deterministic_fallback(request, content_type=request.intervention_type), None

        try:
            if request.intervention_type == "contrast":
                content = await self.provider.generate_contrast_exercise(request)
            elif request.intervention_type == "prerequisite":
                content = await self.provider.generate_prerequisite_lesson(request)
            elif request.intervention_type == "mnemonic":
                content = await self.provider.suggest_mnemonic_alternatives(request)
            else:
                content = await self.provider.explain_diagnosis(request)
        except AIProviderUnavailableError as exc:
            return "unavailable", deterministic_fallback(request, content_type=request.intervention_type), str(exc)
        except CoachContentRejected as exc:
            return "rejected", deterministic_fallback(request, content_type=request.intervention_type), str(exc)
        return "ok", content, None
