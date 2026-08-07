"""Diagnosis-to-intervention planning (issue #185)."""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    DIAGNOSIS_UNKNOWN,
    Diagnosis,
    DiagnosisEvidence,
    InterventionOutcome,
    InterventionPlan,
)
from app.domain.services.diagnosis_engine import DiagnosisCategory
from app.domain.services.intervention_planning import (
    POLICY_VERSION,
    InterventionStrategy,
    evaluate_intervention_outcome,
    is_duplicate_of_active_plan,
    plan_intervention,
)

BASE = datetime(2026, 8, 6, 9, 0)
WORD = 1
USER = 1


def _evidence() -> tuple[DiagnosisEvidence, ...]:
    return (DiagnosisEvidence(kind="test", observation_ids=("o1",), weight=0.8, description="d"),)


def _diagnosis(outcome: str, **overrides) -> Diagnosis:
    fields = dict(
        word_id=WORD, user_id=USER, outcome=outcome, evidence=_evidence(),
        confidence=0.8, rules_version=1, diagnosed_at=BASE, sample_size=3,
    )
    fields.update(overrides)
    return Diagnosis(**fields)


def test_an_abstention_produces_no_plan():
    assert plan_intervention(_diagnosis(DIAGNOSIS_UNKNOWN)) is None
    assert plan_intervention(_diagnosis(DIAGNOSIS_INSUFFICIENT_EVIDENCE)) is None


def test_an_unrecognised_outcome_string_produces_no_plan():
    """Defensive: an outcome that isn't even a DiagnosisCategory member
    (a future addition this module hasn't been updated for, or a bad
    fixture) must not crash the planner."""
    assert plan_intervention(_diagnosis("something_new")) is None


def test_every_real_diagnosis_category_maps_to_a_justified_strategy():
    """TODO 0's own verify clause, positive half: every diagnosed category
    (not an abstention) produces a plan with a stated rationale."""
    for category in DiagnosisCategory:
        if category.value in (DIAGNOSIS_UNKNOWN, DIAGNOSIS_INSUFFICIENT_EVIDENCE):
            continue
        plan = plan_intervention(_diagnosis(category.value))
        assert plan is not None, f"{category} produced no plan"
        assert plan.eligible is True
        assert plan.rationale
        assert plan.strategy in {s.value for s in InterventionStrategy}


def test_exact_confusion_starts_at_isolate():
    """TODO 1: a fresh confusion is staged, not contrasted immediately."""
    plan = plan_intervention(_diagnosis(DiagnosisCategory.EXACT_CONFUSION.value, related_word_id=99))
    assert plan.strategy == InterventionStrategy.ISOLATE.value
    assert plan.second_word_id == 99


def test_exact_confusion_without_a_pair_id_still_stages_isolate():
    """A hand-built fixture with no related_word_id must not crash — it
    falls back to the conservative first stage."""
    plan = plan_intervention(_diagnosis(DiagnosisCategory.EXACT_CONFUSION.value))
    assert plan.strategy == InterventionStrategy.ISOLATE.value
    assert plan.second_word_id is None


def test_confusion_escalates_to_contrast_after_isolated_recall_is_demonstrated():
    """TODO 1's own verify clause: fixtures distinguish "separate now" from
    "contrast now" — one global rule cannot handle both."""
    diagnosis = _diagnosis(DiagnosisCategory.EXACT_CONFUSION.value, related_word_id=99)
    prior_isolate_plan = InterventionPlan(
        word_id=WORD, user_id=USER, diagnosis_outcome=DiagnosisCategory.EXACT_CONFUSION.value,
        strategy=InterventionStrategy.ISOLATE.value, policy_version=POLICY_VERSION, eligible=True,
        rationale="r", planned_at=BASE, second_word_id=99,
    )
    effective_outcome = InterventionOutcome(
        word_id=WORD, user_id=USER, strategy=InterventionStrategy.ISOLATE.value,
        completed=True, result="effective", recorded_at=BASE, horizon="7d",
    )

    plan = plan_intervention(
        diagnosis, prior_plans=(prior_isolate_plan,), prior_outcomes=(effective_outcome,),
    )

    assert plan.strategy == InterventionStrategy.CONTRAST.value
    assert plan.second_word_id == 99


def test_confusion_stays_at_isolate_when_prior_outcome_is_not_yet_effective():
    diagnosis = _diagnosis(DiagnosisCategory.EXACT_CONFUSION.value, related_word_id=99)
    prior_isolate_plan = InterventionPlan(
        word_id=WORD, user_id=USER, diagnosis_outcome=DiagnosisCategory.EXACT_CONFUSION.value,
        strategy=InterventionStrategy.ISOLATE.value, policy_version=POLICY_VERSION, eligible=True,
        rationale="r", planned_at=BASE, second_word_id=99,
    )
    inconclusive_outcome = InterventionOutcome(
        word_id=WORD, user_id=USER, strategy=InterventionStrategy.ISOLATE.value,
        completed=True, result="inconclusive", recorded_at=BASE, horizon="7d",
    )

    plan = plan_intervention(
        diagnosis, prior_plans=(prior_isolate_plan,), prior_outcomes=(inconclusive_outcome,),
    )

    assert plan.strategy == InterventionStrategy.ISOLATE.value


def test_confusion_does_not_escalate_from_a_different_pairs_isolate_outcome():
    """An "effective" isolate outcome for a *different* competitor must not
    leak into staging this pair."""
    diagnosis = _diagnosis(DiagnosisCategory.EXACT_CONFUSION.value, related_word_id=99)
    other_pair_plan = InterventionPlan(
        word_id=WORD, user_id=USER, diagnosis_outcome=DiagnosisCategory.EXACT_CONFUSION.value,
        strategy=InterventionStrategy.ISOLATE.value, policy_version=POLICY_VERSION, eligible=True,
        rationale="r", planned_at=BASE, second_word_id=7,
    )
    effective_outcome = InterventionOutcome(
        word_id=WORD, user_id=USER, strategy=InterventionStrategy.ISOLATE.value,
        completed=True, result="effective", recorded_at=BASE, horizon="7d",
    )

    plan = plan_intervention(
        diagnosis, prior_plans=(other_pair_plan,), prior_outcomes=(effective_outcome,),
    )

    assert plan.strategy == InterventionStrategy.ISOLATE.value


def test_missing_prerequisite_maps_to_prerequisite_path():
    plan = plan_intervention(_diagnosis(DiagnosisCategory.MISSING_PREREQUISITE.value))
    assert plan.strategy == InterventionStrategy.PREREQUISITE_PATH.value


def test_forgetting_and_weak_acquisition_both_map_to_acquisition_restart():
    forgetting = plan_intervention(_diagnosis(DiagnosisCategory.FORGETTING.value))
    weak = plan_intervention(_diagnosis(DiagnosisCategory.WEAK_ACQUISITION.value))
    assert forgetting.strategy == InterventionStrategy.ACQUISITION_RESTART.value
    assert weak.strategy == InterventionStrategy.ACQUISITION_RESTART.value


def test_spatial_anchor_is_never_auto_selected():
    """User-invoked, not diagnosis-triggered — no category maps to it."""
    for category in DiagnosisCategory:
        plan = plan_intervention(_diagnosis(category.value))
        if plan is not None:
            assert plan.strategy != InterventionStrategy.SPATIAL_ANCHOR.value


def test_a_plan_carries_the_diagnosis_it_was_made_from():
    diagnosis = _diagnosis(DiagnosisCategory.EXACT_CONFUSION.value, word_id=42, user_id=7)

    plan = plan_intervention(diagnosis)

    assert plan.word_id == 42
    assert plan.user_id == 7


# --- TODO 2: prerequisite ranking ---


def _graph_with_edges(target_level="B1", *edges):
    from app.domain.services.knowledge_graph import KnowledgeGraph, WordNode

    ids = {w for e in edges for w in (e.source_id, e.target_id)}
    nodes = [
        WordNode(word_id=i, term=str(i), cefr_level="A1" if i != WORD else target_level)
        for i in ids | {WORD}
    ]
    return KnowledgeGraph(nodes, list(edges))


def test_missing_prerequisite_ranks_candidates_by_edge_strength():
    from app.domain.services.knowledge_graph import KnowledgeEdge, Relation

    graph = _graph_with_edges(
        "B1",
        KnowledgeEdge(source_id=WORD, target_id=10, relation=Relation.TOPIC, evidence="e", occurrences=1),
        KnowledgeEdge(source_id=WORD, target_id=20, relation=Relation.SYNONYM, evidence="e", occurrences=3),
    )
    diagnosis = _diagnosis(DiagnosisCategory.MISSING_PREREQUISITE.value)

    plan = plan_intervention(diagnosis, graph=graph)

    # SYNONYM (0.8 base, 3 occurrences) outranks TOPIC (0.3 base).
    assert plan.prerequisite_ids == (20, 10)


def test_missing_prerequisite_dedupes_and_caps_at_three():
    from app.domain.services.knowledge_graph import KnowledgeEdge, Relation

    graph = _graph_with_edges(
        "B1",
        KnowledgeEdge(source_id=WORD, target_id=10, relation=Relation.SYNONYM, evidence="e", occurrences=1),
        # A second, weaker edge between the same pair must not double-count 10.
        KnowledgeEdge(source_id=WORD, target_id=10, relation=Relation.TOPIC, evidence="e", occurrences=1),
        KnowledgeEdge(source_id=WORD, target_id=11, relation=Relation.SYNONYM, evidence="e", occurrences=1),
        KnowledgeEdge(source_id=WORD, target_id=12, relation=Relation.SYNONYM, evidence="e", occurrences=1),
        KnowledgeEdge(source_id=WORD, target_id=13, relation=Relation.SYNONYM, evidence="e", occurrences=1),
    )
    diagnosis = _diagnosis(DiagnosisCategory.MISSING_PREREQUISITE.value)

    plan = plan_intervention(diagnosis, graph=graph)

    assert len(plan.prerequisite_ids) == 3
    assert len(set(plan.prerequisite_ids)) == 3


def test_missing_prerequisite_without_a_graph_still_produces_a_plan():
    """Missing/CEFR evidence remains unknown, not a crash — an unranked
    plan is still eligible."""
    diagnosis = _diagnosis(DiagnosisCategory.MISSING_PREREQUISITE.value)

    plan = plan_intervention(diagnosis)

    assert plan.eligible is True
    assert plan.prerequisite_ids == ()


# --- TODO 4: idempotency ---


def test_a_second_identical_plan_is_recognised_as_a_duplicate_of_an_active_one():
    candidate = plan_intervention(_diagnosis(DiagnosisCategory.FORGETTING.value))
    prior = InterventionPlan(
        word_id=WORD, user_id=USER, diagnosis_outcome=DiagnosisCategory.FORGETTING.value,
        strategy=InterventionStrategy.ACQUISITION_RESTART.value, policy_version=POLICY_VERSION,
        eligible=True, rationale="r", planned_at=BASE,
    )

    assert is_duplicate_of_active_plan(candidate, (prior,), ()) is True


def test_a_plan_is_not_a_duplicate_once_a_terminal_outcome_is_recorded():
    candidate = plan_intervention(_diagnosis(DiagnosisCategory.FORGETTING.value))
    prior = InterventionPlan(
        word_id=WORD, user_id=USER, diagnosis_outcome=DiagnosisCategory.FORGETTING.value,
        strategy=InterventionStrategy.ACQUISITION_RESTART.value, policy_version=POLICY_VERSION,
        eligible=True, rationale="r", planned_at=BASE,
    )
    resolved = InterventionOutcome(
        word_id=WORD, user_id=USER, strategy=InterventionStrategy.ACQUISITION_RESTART.value,
        completed=True, result="resolved", recorded_at=BASE,
    )

    assert is_duplicate_of_active_plan(candidate, (prior,), (resolved,)) is False


def test_a_plan_is_not_a_duplicate_when_nothing_prior_matches():
    candidate = plan_intervention(_diagnosis(DiagnosisCategory.FORGETTING.value))
    assert is_duplicate_of_active_plan(candidate, (), ()) is False


# --- TODO 5: delayed outcome evaluation ---


def test_outcome_is_inconclusive_below_the_minimum_sample_size():
    assert evaluate_intervention_outcome(pre_correct=0, pre_total=1, post_correct=1, post_total=1) == "inconclusive"


def test_outcome_is_effective_when_accuracy_improves():
    assert evaluate_intervention_outcome(pre_correct=1, pre_total=4, post_correct=3, post_total=4) == "effective"


def test_outcome_is_ineffective_when_accuracy_worsens():
    assert evaluate_intervention_outcome(pre_correct=3, pre_total=4, post_correct=1, post_total=4) == "ineffective"


def test_outcome_is_inconclusive_when_accuracy_is_unchanged():
    assert evaluate_intervention_outcome(pre_correct=2, pre_total=4, post_correct=2, post_total=4) == "inconclusive"
