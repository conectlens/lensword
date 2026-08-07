"""Bounded exploration/exploitation over intervention strategies (#186 TODO 3).

An epsilon-greedy selector, not UCB: simpler to reason about and test, and
its exploration rate is a constant that never decays toward zero — the
issue's own verify clause ("no permanent lock-in after early noise") rules
out any schedule whose exploration probability could converge to zero, which
a naive UCB-style confidence-bound schedule can do once one arm's trial
count dominates.

Zero wall-clock or global-`random` dependency, matching this package's own
architecture rule (enforced for the sibling diagnosis modules by
`tests/test_diagnosis_architecture_boundary.py`, which parses this whole
package): every call that needs randomness takes an injected
`rng: Callable[[], float]` returning a value in `[0, 1)`, built by the
*caller* (e.g. `random.Random(seed).random`, application-layer only) so a
fixed seed reproduces an identical run byte-for-byte. Nothing in this module
imports `random` or `datetime.now`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

# Explore this fraction of selections regardless of history. A constant
# rather than a decaying schedule (see module docstring): TODO 3 explicitly
# requires exploration to continue indefinitely, not just during a warm-up
# period, so a strategy that looked bad on early noisy trials always keeps
# getting re-tried at this rate.
DEFAULT_EPSILON = 0.15


@dataclass(frozen=True)
class ArmStats:
    """One strategy's running record. Immutable — `record_result` returns a
    new tuple of arms rather than mutating one in place, the same
    append-only-record posture every other domain type in this epic uses."""

    strategy: str
    successes: int = 0
    trials: int = 0

    def __post_init__(self) -> None:
        if self.trials < 0 or self.successes < 0:
            raise ValueError("ArmStats counts cannot be negative")
        if self.successes > self.trials:
            raise ValueError("ArmStats cannot have more successes than trials")

    @property
    def mean(self) -> float:
        return self.successes / self.trials if self.trials else 0.0

    def with_result(self, *, success: bool) -> "ArmStats":
        return replace(self, successes=self.successes + int(success), trials=self.trials + 1)


def reset_arms(strategies: Sequence[str]) -> tuple[ArmStats, ...]:
    """TODO 3's explicit reset: a fresh set of untried arms. Used both to
    seed a brand-new selection policy and to give a learner who opts back
    into adaptive selection (after opting out, or after requesting a reset)
    a clean slate rather than carrying forward whatever an earlier run
    concluded."""
    if not strategies:
        raise ValueError("reset_arms requires at least one strategy")
    if len(set(strategies)) != len(strategies):
        raise ValueError("reset_arms requires distinct strategy names")
    return tuple(ArmStats(strategy=s) for s in strategies)


def select_strategy(
    arms: Sequence[ArmStats],
    *,
    rng: Callable[[], float],
    epsilon: float = DEFAULT_EPSILON,
    override: str | None = None,
) -> str:
    """Pick the next strategy to try.

    `override` is an explicit learner preference or accessibility
    requirement (TODO 3: "respect accessibility/explicit preference
    regardless of measured performance"). When set, it is returned
    unconditionally — never weighed against, blended with, or overridden by
    `arms`' measured performance, however strong that evidence is. This is
    also how TODO 3's opt-out is expressed: a caller who wants selection
    disabled passes a fixed `override` every time and this function never
    even evaluates `arms`.
    """
    if not arms:
        raise ValueError("select_strategy requires at least one arm")
    if not 0.0 <= epsilon <= 1.0:
        raise ValueError("epsilon must be in [0, 1]")
    if override is not None:
        if not any(a.strategy == override for a in arms):
            raise ValueError(f"override strategy {override!r} is not one of the given arms")
        return override

    untried = [a for a in arms if a.trials == 0]
    # An untried arm is never worse than an epsilon-driven exploration pick,
    # so it is tried before any exploit/explore coin flip — this is what
    # guarantees every arm gets a first trial rather than epsilon (a small
    # constant) taking arbitrarily long to reach a low-probability arm by
    # chance alone.
    if untried:
        index = min(int(rng() * len(untried)), len(untried) - 1)
        return untried[index].strategy

    if rng() < epsilon:
        index = min(int(rng() * len(arms)), len(arms) - 1)
        return arms[index].strategy

    # Exploit: highest empirical success rate. Ties broken by strategy name
    # (not by rng) so exploitation itself is deterministic given the same
    # arms — only the explore/exploit coin flip above consumes randomness.
    best = max(arms, key=lambda a: (a.mean, a.strategy))
    return best.strategy


def record_result(arms: Sequence[ArmStats], strategy: str, *, success: bool) -> tuple[ArmStats, ...]:
    """Apply one observed result to the matching arm, leaving the others
    untouched. Raises if `strategy` names no arm — a silent no-op here would
    hide a caller bug (a strategy the planner produced that this policy was
    never told about)."""
    if not any(a.strategy == strategy for a in arms):
        raise ValueError(f"{strategy!r} is not one of the given arms")
    return tuple(a.with_result(success=success) if a.strategy == strategy else a for a in arms)
