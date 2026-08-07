"""Links raw `LearningObservation`/`InterventionPlan` history into the
comparable `InterventionObservation` records `intervention_efficacy.py`
consumes (#186 TODO 1: "outcome attribution: link delayed observations to
plans + comparable controls").

Honest scope note (documented here and in the PR, matching this codebase's
own house style): production has no randomized control group — a word is
either given an intervention plan or it is not, nobody is deliberately held
back for comparison. This module's control arm is therefore an approximation:
a word's own organic review history (observations never linked to any
plan) at a comparable elapsed-time bucket, not a matched or randomized
cohort. That is real, already-collected data and a defensible baseline
("how did this learner do on this kind of item without this intervention"),
but it is not a randomized trial, and a future phase with enough plan volume
to matched-pair learners/items should replace it with one.

Pure and deterministic (no repository, no I/O, no wall clock) — the
application layer fetches `LearningObservation`/`InterventionPlan` rows and
a per-word context dict and passes them in, the same seam
`intervention_planning.py` uses for the knowledge graph and prior
plans/outcomes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from app.domain.services.diagnosis_contracts import InterventionPlan, LearningObservation
from app.domain.services.intervention_efficacy import InterventionObservation
from app.domain.value_objects import ReviewOutcome

# Retention horizons this module can bucket an elapsed-day count into.
# Fixed and small on purpose: `intervention_efficacy.EfficacyContext`
# compares by exact `horizon_days` equality, so an unbounded range of raw
# elapsed-day counts would make every comparison a singleton that never
# reaches `minimum_samples`. 1/7/30 mirror the checkpoints
# `EvaluateInterventionOutcomesUseCase` already measures (24h/7d) plus a
# longer-range bucket for older organic evidence.
HORIZON_BUCKETS: tuple[int, ...] = (1, 7, 30)


def _bucket_horizon(elapsed_days: int) -> int:
    elapsed_days = max(elapsed_days, 0)
    return min(HORIZON_BUCKETS, key=lambda bucket: abs(bucket - elapsed_days))


def _mastery_bucket(prior_total: int, prior_correct: int) -> str:
    """"new" (never seen before), else "weak"/"strong" split at 50% prior
    accuracy — coarse on purpose (see intervention_efficacy._CONFOUND_*
    thresholds' own reasoning: a few wide buckets are less likely to
    over-fit noise than a continuous prior-accuracy comparison would be)."""
    if prior_total == 0:
        return "new"
    return "strong" if (prior_correct / prior_total) >= 0.5 else "weak"


@dataclass(frozen=True)
class WordEfficacyContext:
    """The per-word facts attribution needs that live on `Word`, not on any
    observation — kept as a small local shape so this module does not need
    to import the `Word` entity (a domain-layer service should not depend on
    another aggregate's full shape for three fields)."""

    item_class: str
    language: str
    difficulty: str
    created_at: datetime


def attribute_efficacy_observations(
    *,
    learner_id: int,
    observations: Sequence[LearningObservation],
    plans: Sequence[InterventionPlan],
    word_contexts: Mapping[int, WordEfficacyContext],
) -> list[InterventionObservation]:
    """Turn one learner's raw observation/plan history into
    `InterventionObservation` rows `estimate_efficacy` can compare.

    Attribution rule: an observation linked to a plan
    (`LearningObservation.intervention_plan_ref` is set) is that plan's
    strategy's intervention-arm evidence, at the horizon bucketed from time
    since the *most recent* plan covering it. An observation with no plan
    link is organic — control-arm evidence, bucketed from time since the
    word's own `created_at` — reused as the control baseline for every
    strategy this word has ever had a plan for, since there is exactly one
    organic history per word, not one per strategy compared against it.
    A word with no plans at all contributes no observations here (there is
    nothing yet to compare its organic history against).
    """
    by_word: dict[int, list[LearningObservation]] = defaultdict(list)
    for observation in observations:
        by_word[observation.word_id].append(observation)

    plans_by_word: dict[int, list[tuple[str, datetime]]] = defaultdict(list)
    for plan in plans:
        plans_by_word[plan.word_id].append((plan.strategy, plan.planned_at))

    result: list[InterventionObservation] = []
    for word_id, entries in by_word.items():
        context = word_contexts.get(word_id)
        word_plans = plans_by_word.get(word_id)
        if context is None or not word_plans:
            continue
        entries = sorted(entries, key=lambda o: o.observed_at)

        prior_total = 0
        prior_correct = 0
        for index, observation in enumerate(entries, start=1):
            correct = observation.outcome is ReviewOutcome.CORRECT
            mastery = _mastery_bucket(prior_total, prior_correct)
            is_control = observation.intervention_plan_ref is None

            if is_control:
                anchor = context.created_at
                elapsed = (observation.observed_at - anchor).days
                horizon_days = _bucket_horizon(elapsed)
                target_strategies = sorted({strategy for strategy, _ in word_plans})
            else:
                covering = [
                    planned_at for strategy, planned_at in word_plans if planned_at <= observation.observed_at
                ]
                if not covering:
                    # A plan-linked observation whose plan is not in
                    # `plans` (a caller passed a partial plan list) — skip
                    # rather than guess an anchor.
                    prior_total += 1
                    prior_correct += int(correct)
                    continue
                anchor = max(covering)
                elapsed = (observation.observed_at - anchor).days
                horizon_days = _bucket_horizon(elapsed)
                current_strategies = [
                    strategy for strategy, planned_at in word_plans if planned_at == anchor
                ]
                target_strategies = sorted(set(current_strategies))

            for strategy in target_strategies:
                result.append(
                    InterventionObservation(
                        evidence_id=observation.observation_id,
                        learner_id=learner_id,
                        item_id=word_id,
                        # Same-calendar-day attempts on the same word collapse
                        # to one exposure — TODO 1's "don't count several
                        # immediate repetitions as independent successes",
                        # applied at attribution time rather than trusting
                        # every caller to pre-collapse its input.
                        exposure_id=f"{word_id}:{observation.observed_at.date()}",
                        intervention_type=strategy,
                        item_class=context.item_class,
                        language=context.language,
                        prompt_direction=observation.prompt_direction or "unspecified",
                        difficulty=context.difficulty,
                        modality=observation.modality or "unspecified",
                        horizon_days=horizon_days,
                        correct=correct,
                        is_control=is_control,
                        observed_at=observation.observed_at,
                        prior_mastery=mastery,
                        exposure_count=index,
                    )
                )

            prior_total += 1
            prior_correct += int(correct)

    return result
