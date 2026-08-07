"""The software-concepts domain-kernel spike (#189 TODO 2).

TODO 2's own verify clause: "the spike uses the core diagnosis/intervention
services without language-specific branches inside them." Every diagnosis
and plan below comes from the unmodified `diagnose()`/`plan_intervention()`
functions `diagnosis_engine.py`/`intervention_planning.py` already ship for
vocabulary — this file never imports a modified copy of either, because
none exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.application.use_cases.domain_kernel_spike import RunSoftwareConceptSpikeUseCase
from app.domain.entities import RecallSettings
from app.domain.exceptions import PermissionDeniedError
from app.domain.services import software_concepts_spike as spike
from app.domain.services.diagnosis_engine import DiagnosisCategory, diagnose
from app.domain.services.diagnosis_contracts import InterventionOutcome
from app.domain.services.domain_kernel import build_diagnosis_context, observation_from_evaluation
from app.domain.services.intervention_efficacy import (
    EfficacyContext,
    EfficacyStatus,
    InterventionObservation,
    estimate_efficacy,
)
from app.domain.services.intervention_planning import InterventionStrategy, plan_intervention

BASE = datetime(2026, 8, 7, 9, 0)
USER = 1


def _confusion_observations(item_id: str, confused_answer: str, count: int = 2) -> tuple:
    evaluator = spike.ExactLabelAnswerEvaluator()
    item = spike.CATALOG[item_id]
    return tuple(
        observation_from_evaluation(
            observation_id=f"{item_id}-{i}",
            item=item,
            user_id=USER,
            evaluation=evaluator.evaluate(item_id, confused_answer),
            observed_at=BASE + timedelta(days=i * 2),
            attempted_answer=confused_answer,
        )
        for i in range(count)
    )


# --- Full cycle for a confusion pair (TODO 2's required verify test) -------


def test_full_cycle_for_a_software_concept_confusion_pair():
    """Evidence -> diagnosis -> intervention -> delayed outcome, for
    'thread' repeatedly answered as 'process', using nothing but the
    generic kernel (`domain_kernel.py`, `software_concepts_spike.py`) and
    the existing engine functions."""
    item_provider = spike.SoftwareConceptItemProvider()
    similarity_source = spike.StaticConfusionPairs()
    content_source = spike.TemplatedContentSource()

    thread = item_provider.get_item("thread")
    observations = _confusion_observations("thread", "process")

    # 1. Evidence -> diagnosis, via the unmodified diagnose().
    context = build_diagnosis_context(
        item=thread, user_id=USER, observations=observations,
        catalog=spike.CATALOG, similarity_source=similarity_source,
    )
    diagnosis = diagnose(context)
    assert diagnosis.outcome == DiagnosisCategory.EXACT_CONFUSION.value
    assert not diagnosis.is_abstention
    assert diagnosis.evidence

    # 2. Diagnosis -> intervention, via the unmodified plan_intervention().
    # A first-time confusion diagnosis stages to ISOLATE, not CONTRAST
    # directly (#185 TODO 1's staging policy) — CONTRAST only follows a
    # prior, recorded-effective ISOLATE plan for this exact pair, which
    # this spike does not fabricate.
    plan = plan_intervention(diagnosis)
    assert plan is not None
    assert plan.strategy == InterventionStrategy.ISOLATE.value

    # 3. Intervention -> content, via the kernel's own content protocol.
    content = content_source.content_for(
        strategy=plan.strategy, item_id="thread", item_label=thread.label, other_label="process",
    )
    assert "thread" in content.prompt
    assert "process" in content.prompt

    # 4. Delayed verification: days later (not a same-session repeat), the
    # learner now answers correctly.
    evaluator = spike.ExactLabelAnswerEvaluator()
    delayed = evaluator.evaluate("thread", "thread")
    assert delayed.correct

    outcome = InterventionOutcome(
        word_id=thread.numeric_id, user_id=USER, strategy=plan.strategy, completed=True,
        result="resolved", recorded_at=BASE + timedelta(days=5), completed_at=BASE + timedelta(days=5),
    )
    assert outcome.completed and outcome.result == "resolved"

    # 5. Delayed-outcome measurement: the same intervention_efficacy.py
    # vocabulary already uses, scoped to a software-concept item_class,
    # comparing the isolate-intervention arm (thread/process) against an
    # unintervened control arm (stack/heap). learner_id/modality are both
    # required context axes (#186 TODO 0/TODO 1) — this test supplies real
    # values for both rather than defaults, the same as any real caller must.
    intervention_arm = [
        InterventionObservation(
            evidence_id=f"thread-delayed-{i}", learner_id=USER, item_id=thread.numeric_id,
            exposure_id=f"exp-thread-{i}", intervention_type=plan.strategy, item_class="software_concept",
            language="n/a", prompt_direction="concept_to_label", difficulty="n/a", modality="text",
            horizon_days=5, correct=True, is_control=False, observed_at=BASE + timedelta(days=5 + i),
        )
        for i in range(2)
    ]
    control_arm = [
        InterventionObservation(
            evidence_id=f"stack-delayed-{i}", learner_id=USER, item_id=spike.CATALOG["stack"].numeric_id,
            exposure_id=f"exp-stack-{i}", intervention_type=plan.strategy, item_class="software_concept",
            language="n/a", prompt_direction="concept_to_label", difficulty="n/a", modality="text",
            horizon_days=5, correct=False, is_control=True, observed_at=BASE + timedelta(days=5 + i),
        )
        for i in range(2)
    ]
    estimate = estimate_efficacy(
        intervention_arm + control_arm,
        intervention_type=plan.strategy,
        context=EfficacyContext(
            learner_id=USER, item_class="software_concept", language="n/a",
            prompt_direction="concept_to_label", difficulty="n/a", modality="text", horizon_days=5,
        ),
        minimum_samples=2,
    )
    assert estimate.status is EfficacyStatus.MEASURED
    assert estimate.effect is not None and estimate.effect > 0
    assert estimate.recommendation is not None


# --- A second category (not just confusion) genuinely works too -----------


def test_weak_acquisition_fires_for_repeated_failure_with_no_prior_recall():
    from app.domain.value_objects import ReviewOutcome

    stack = spike.CATALOG["stack"]
    evaluator = spike.ExactLabelAnswerEvaluator()
    observations = tuple(
        observation_from_evaluation(
            observation_id=f"stack-fail-{i}", item=stack, user_id=USER,
            evaluation=evaluator.evaluate("stack", "wrong answer"),
            observed_at=BASE + timedelta(days=i * 2), attempted_answer="wrong answer",
        )
        for i in range(2)
    )
    context = build_diagnosis_context(item=stack, user_id=USER, observations=observations, catalog=spike.CATALOG)
    diagnosis = diagnose(context)
    assert diagnosis.outcome == DiagnosisCategory.WEAK_ACQUISITION.value
    assert all(o.outcome is ReviewOutcome.INCORRECT for o in observations)


# --- Prerequisite modeling: a real finding, not a clean adapter -----------


def test_missing_prerequisite_fires_via_the_borrowed_cefr_ordinal(monkeypatch=None):
    """Documents the friction TODO 0's audit predicted:
    `MissingPrerequisiteRule` only fires through `KnowledgeGraph`'s own
    CEFR-ordinal comparison and 'any edge' connectivity, both built for
    vocabulary. The spike exercises the rule by reusing those mechanisms
    exactly as they exist, rather than adding a first-class prerequisite
    relation to the core graph — see docs/adr/0009-domain-neutral-kernel.md
    for why that stays out of scope for one spike."""
    authorization = spike.CATALOG["authorization"]
    evaluator = spike.ExactLabelAnswerEvaluator()
    observations = tuple(
        observation_from_evaluation(
            observation_id=f"authz-fail-{i}", item=authorization, user_id=USER,
            evaluation=evaluator.evaluate("authorization", "not authorization"),
            observed_at=BASE + timedelta(days=i * 2), attempted_answer="not authorization",
        )
        for i in range(2)
    )
    context = build_diagnosis_context(
        item=authorization, user_id=USER, observations=observations, catalog=spike.CATALOG,
        prerequisite_source=spike.AuthPrerequisiteSource(),
    )
    diagnosis = diagnose(context)
    assert diagnosis.outcome == DiagnosisCategory.MISSING_PREREQUISITE.value

    plan = plan_intervention(diagnosis)
    assert plan is not None
    assert plan.strategy == InterventionStrategy.PREREQUISITE_PATH.value


# --- The developer-flag gate ------------------------------------------------


def test_spike_use_case_is_disabled_by_default():
    settings = RecallSettings(user_id=USER)
    assert settings.domain_kernel_spike_enabled is False
    with pytest.raises(PermissionDeniedError):
        RunSoftwareConceptSpikeUseCase().execute(settings, user_id=USER)


def test_spike_use_case_runs_the_full_cycle_once_enabled():
    settings = RecallSettings(user_id=USER, domain_kernel_spike_enabled=True)
    result = RunSoftwareConceptSpikeUseCase().execute(settings, user_id=USER)
    assert result.diagnosis.outcome == DiagnosisCategory.EXACT_CONFUSION.value
    assert result.plan is not None
    assert result.plan.strategy == InterventionStrategy.ISOLATE.value
    assert result.content is not None
    assert result.outcome is not None and result.outcome.completed
