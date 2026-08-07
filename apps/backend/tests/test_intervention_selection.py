import random

import pytest

from app.domain.services.intervention_selection import (
    ArmStats,
    DEFAULT_EPSILON,
    record_result,
    reset_arms,
    select_strategy,
)


def test_reset_arms_gives_a_fresh_untried_set():
    arms = reset_arms(["contrast", "isolate", "mnemonic_replacement"])
    assert len(arms) == 3
    assert all(a.trials == 0 and a.successes == 0 for a in arms)


def test_reset_arms_rejects_duplicate_strategies():
    with pytest.raises(ValueError):
        reset_arms(["contrast", "contrast"])


def test_reset_arms_rejects_empty_input():
    with pytest.raises(ValueError):
        reset_arms([])


def test_override_always_wins_regardless_of_measured_performance():
    """#186 TODO 3: "respect accessibility/explicit preference regardless
    of measured performance." A strategy with a perfect record must lose to
    an explicit override naming a different, unproven strategy."""
    arms = (
        ArmStats("contrast", successes=50, trials=50),
        ArmStats("spatial_anchor", successes=0, trials=10),
    )
    chosen = select_strategy(arms, rng=lambda: 0.99, override="spatial_anchor")
    assert chosen == "spatial_anchor"


def test_override_naming_an_unknown_arm_is_rejected():
    arms = reset_arms(["contrast"])
    with pytest.raises(ValueError):
        select_strategy(arms, rng=lambda: 0.5, override="not_an_arm")


def test_untried_arms_are_tried_before_any_exploit_or_explore_choice():
    """Even an rng that would always choose to exploit (never explore) must
    not starve an arm that has never been tried."""
    arms = (
        ArmStats("contrast", successes=9, trials=10),
        ArmStats("isolate", successes=0, trials=0),
    )
    chosen = select_strategy(arms, rng=lambda: 0.0, epsilon=DEFAULT_EPSILON)
    assert chosen == "isolate"


def test_selection_is_deterministic_given_the_same_seed():
    strategies = ["contrast", "isolate", "context_variation"]
    sequence_a = _simulate(strategies, seed=123, rounds=50)
    sequence_b = _simulate(strategies, seed=123, rounds=50)
    assert sequence_a == sequence_b


def test_different_seeds_can_diverge():
    strategies = ["contrast", "isolate", "context_variation"]
    sequence_a = _simulate(strategies, seed=1, rounds=50)
    sequence_b = _simulate(strategies, seed=2, rounds=50)
    assert sequence_a != sequence_b


def _simulate(strategies, *, seed: int, rounds: int) -> list[str]:
    arms = reset_arms(strategies)
    rng = random.Random(seed).random
    outcomes = random.Random(seed + 1)
    selections = []
    for _ in range(rounds):
        strategy = select_strategy(arms, rng=rng)
        selections.append(strategy)
        arms = record_result(arms, strategy, success=outcomes.random() < 0.5)
    return selections


def test_continued_exploration_and_no_permanent_lock_in_after_early_noise():
    """#186 TODO 3's own verify clause: a deterministic seeded simulation
    where one strategy looks like an early winner (by chance) must not
    permanently suppress a genuinely better alternative — exploration has to
    continue long enough for the truth to surface."""
    # `contrast` already has a perfect early record (a lucky early winner);
    # `isolate` has never been tried yet, despite genuinely being the better
    # strategy below.
    arms: tuple[ArmStats, ...] = (
        ArmStats("contrast", successes=4, trials=4),
        ArmStats("isolate", successes=0, trials=0),
    )
    policy_rng = random.Random(42).random
    outcome_rng = random.Random(99)
    true_rate = {"contrast": 0.3, "isolate": 0.7}

    selections: list[str] = []
    for _ in range(500):
        strategy = select_strategy(arms, rng=policy_rng)
        selections.append(strategy)
        success = outcome_rng.random() < true_rate[strategy]
        arms = record_result(arms, strategy, success=success)

    contrast_stats = next(a for a in arms if a.strategy == "contrast")
    isolate_stats = next(a for a in arms if a.strategy == "isolate")

    # Continued exploration: isolate was not starved after its slow start.
    assert isolate_stats.trials > 30
    # No permanent lock-in: given enough rounds, the genuinely better
    # strategy's measured mean overtakes the early winner's.
    assert isolate_stats.mean > contrast_stats.mean
    # And it is still being selected near the end, not just early on.
    assert "isolate" in selections[-20:]


def test_record_result_only_touches_the_matching_arm():
    arms = reset_arms(["contrast", "isolate"])
    updated = record_result(arms, "contrast", success=True)
    contrast = next(a for a in updated if a.strategy == "contrast")
    isolate = next(a for a in updated if a.strategy == "isolate")
    assert contrast.trials == 1 and contrast.successes == 1
    assert isolate.trials == 0


def test_record_result_rejects_unknown_strategy():
    arms = reset_arms(["contrast"])
    with pytest.raises(ValueError):
        record_result(arms, "not_an_arm", success=True)


def test_arm_stats_rejects_impossible_counts():
    with pytest.raises(ValueError):
        ArmStats("contrast", successes=5, trials=3)
