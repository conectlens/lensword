"""Bounded, honest offline comparison of adaptive vs non-adaptive delayed
outcomes (#186 TODO 5).

Deliberately narrow. TODO 5 in full asks for "offline replay / opt-in
cohort analysis" — assigning learners to cohorts, persisting that
assignment, and replaying historical sessions under a counterfactual
policy. None of that ships here: it is real product and infrastructure
work, and the issue itself gates TODO 5 at P2 with "do not start before
intervention outcomes are reliable" — which is what TODO 0-3 in this same
pass exist to establish. What ships here is the one piece that is pure
domain logic regardless of how a future cohort system assigns learners:
a function comparing two already-assembled cohorts' delayed outcomes with
the same INSUFFICIENT_EVIDENCE-below-threshold discipline
`intervention_efficacy.py` uses, plus the threshold constant gating whether
adaptation "would be enabled" from that comparison (#186's own success
metric: "automatic adaptation only above predefined evidence thresholds").

Nothing here claims adaptive selection outperforms the non-adaptive
baseline — that claim requires real usage data this pass does not have.
`compare_cohorts` is the honest mechanism; whether it is ever fed real data
showing outperformance is future work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.services.intervention_efficacy import (
    EfficacyStatus,
    InterventionObservation,
    deduplicate_observations,
    wilson_interval,
)

# Below this, a raw rate difference is noise even when its interval happens
# not to cross zero — matching intervention_efficacy's own conservatism:
# enabling automatic adaptation on a coin-flip-sized effect is worse than
# not adapting at all. A documented judgement call, not derived from a
# formal power calculation (the same honesty `DEFAULT_MAX_AGE_DAYS` in
# intervention_efficacy.py already models).
MINIMUM_ADAPTATION_EFFECT = 0.05

# The default minimum per-cohort sample before even attempting the
# comparison. Higher than `estimate_efficacy`'s default of 5: a cohort-level
# claim ("adaptive selection helps") is a stronger, more consequential
# statement than one scoped technique/context estimate, and warrants more
# evidence before it is even compared.
DEFAULT_MINIMUM_COHORT_SAMPLES = 30


@dataclass(frozen=True)
class CohortComparison:
    status: EfficacyStatus
    adaptive_samples: int
    control_samples: int
    adaptive_rate: float | None
    control_rate: float | None
    effect: float | None
    interval_low: float | None
    interval_high: float | None
    # TODO 5's gate: True only when adaptation would be enabled from this
    # comparison alone (see `compare_cohorts`'s doc for the exact rule).
    # Always False on anything but MEASURED.
    adaptation_recommended: bool
    reason: str | None = None


def compare_cohorts(
    adaptive: Iterable[InterventionObservation],
    control: Iterable[InterventionObservation],
    *,
    minimum_samples: int = DEFAULT_MINIMUM_COHORT_SAMPLES,
) -> CohortComparison:
    """Compare a cohort of delayed outcomes gathered under adaptive
    selection (#186 TODO 3) against a non-adaptive control cohort.

    Reuses `intervention_efficacy.deduplicate_observations` so several
    immediate repetitions in either cohort collapse the same way a single
    technique/context comparison's do — this is a cohort-level rollup of the
    same kind of evidence, not a different kind of measurement.

    `adaptation_recommended` is deliberately conservative: it requires the
    *entire* Wilson-based interval to clear `MINIMUM_ADAPTATION_EFFECT`, not
    just the point estimate, matching the "automatic adaptation only above
    predefined evidence thresholds" success metric.
    """
    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least two")
    adaptive_list = deduplicate_observations(adaptive)
    control_list = deduplicate_observations(control)

    if len(adaptive_list) < minimum_samples or len(control_list) < minimum_samples:
        return CohortComparison(
            status=EfficacyStatus.INSUFFICIENT_EVIDENCE,
            adaptive_samples=len(adaptive_list),
            control_samples=len(control_list),
            adaptive_rate=None,
            control_rate=None,
            effect=None,
            interval_low=None,
            interval_high=None,
            adaptation_recommended=False,
            reason="minimum delayed samples are required in both the adaptive and control cohorts",
        )

    adaptive_successes = sum(o.correct for o in adaptive_list)
    control_successes = sum(o.correct for o in control_list)
    adaptive_rate = adaptive_successes / len(adaptive_list)
    control_rate = control_successes / len(control_list)
    effect = adaptive_rate - control_rate
    a_low, a_high = wilson_interval(adaptive_successes, len(adaptive_list))
    c_low, c_high = wilson_interval(control_successes, len(control_list))
    interval_low = a_low - c_high
    interval_high = a_high - c_low

    return CohortComparison(
        status=EfficacyStatus.MEASURED,
        adaptive_samples=len(adaptive_list),
        control_samples=len(control_list),
        adaptive_rate=adaptive_rate,
        control_rate=control_rate,
        effect=effect,
        interval_low=interval_low,
        interval_high=interval_high,
        adaptation_recommended=interval_low >= MINIMUM_ADAPTATION_EFFECT,
    )
