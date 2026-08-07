"""Runs the software-concepts domain-kernel spike end to end (#189 TODO 2).

The one real, gated entry point for the spike. Everything it calls —
`app.domain.services.domain_kernel`, `app.domain.services.software_concepts_spike`,
and the unmodified `diagnose()`/`plan_intervention()` — is pure and
I/O-free, so this use case adds nothing but the settings gate itself and
the evidence fixture. No repository is touched: the spike does not
persist anything, matching TODO 3's explicit choice not to build a real
domain-pack loader or storage layer for a single spike.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.domain.entities import RecallSettings
from app.domain.exceptions import PermissionDeniedError
from app.domain.services import software_concepts_spike as spike
from app.domain.services.diagnosis_contracts import Diagnosis, InterventionOutcome
from app.domain.services.diagnosis_engine import diagnose
from app.domain.services.domain_kernel import InterventionContent, build_diagnosis_context, observation_from_evaluation
from app.domain.services.intervention_planning import InterventionPlan, plan_intervention
from app.domain.value_objects import utcnow


@dataclass(frozen=True, slots=True)
class SpikeCycleResult:
    """What one evidence -> diagnosis -> intervention -> delayed-outcome
    pass actually produced, for a caller (a test, a dev console) to
    inspect."""

    diagnosis: Diagnosis
    plan: InterventionPlan | None
    content: InterventionContent | None
    outcome: InterventionOutcome | None


class RunSoftwareConceptSpikeUseCase:
    """Evidence -> diagnosis -> intervention -> delayed-outcome for the
    "thread" mistaken for "process" confusion pair, gated behind
    `RecallSettings.domain_kernel_spike_enabled`.

    Disabled accounts get `PermissionDeniedError`, the same domain
    exception `app/api/routers/acquisition.py` already raises (as an HTTP
    403) when `acquisition_loop_enabled` is off — reused here rather than
    inventing a parallel "feature not enabled" exception type.
    """

    def execute(self, settings: RecallSettings, user_id: int = 1) -> SpikeCycleResult:
        if not settings.domain_kernel_spike_enabled:
            raise PermissionDeniedError("The domain-kernel spike is not enabled for this account")

        item_provider = spike.SoftwareConceptItemProvider()
        evaluator = spike.ExactLabelAnswerEvaluator()
        similarity_source = spike.StaticConfusionPairs()
        content_source = spike.TemplatedContentSource()

        thread = item_provider.get_item("thread")
        base = utcnow() - timedelta(days=10)
        # Two genuinely separate attempts (not a same-session repeat),
        # each answering "process" when asked about "thread" — the same
        # evidentiary bar ExactConfusionRule requires for vocabulary.
        observations = tuple(
            observation_from_evaluation(
                observation_id=f"spike-{user_id}-{index}",
                item=thread,
                user_id=user_id,
                evaluation=evaluator.evaluate("thread", "process"),
                observed_at=base + timedelta(days=index * 2),
                attempted_answer="process",
            )
            for index in range(2)
        )

        context = build_diagnosis_context(
            item=thread,
            user_id=user_id,
            observations=observations,
            catalog=spike.CATALOG,
            similarity_source=similarity_source,
        )
        result = diagnose(context)

        plan = plan_intervention(result)
        content: InterventionContent | None = None
        outcome: InterventionOutcome | None = None
        if plan is not None:
            content = content_source.content_for(
                strategy=plan.strategy, item_id="thread", item_label=thread.label, other_label="process"
            )
            outcome = InterventionOutcome(
                word_id=thread.numeric_id,
                user_id=user_id,
                strategy=plan.strategy,
                completed=True,
                result="resolved",
                recorded_at=utcnow(),
                completed_at=utcnow(),
            )

        return SpikeCycleResult(diagnosis=result, plan=plan, content=content, outcome=outcome)
