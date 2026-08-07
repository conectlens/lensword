from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.companion_loop import (
    CompanionLoopBudget,
    CompanionLoopState,
    LoopLimitReached,
    LoopStopReason,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _state(**overrides):
    values = {
        "session_id": "session-1",
        "user_id": 1,
        "budget": CompanionLoopBudget(tool_calls=2, samples=1, activities=5, writes=5),
        "started_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return CompanionLoopState(**values)


def test_reserve_increments_the_matching_counter():
    state = _state()
    state.reserve("tool", 1, now=NOW)
    assert state.tool_calls == 1
    assert state.stopped_reason is None


def test_reserve_stops_the_loop_once_a_budget_is_exceeded():
    state = _state()
    state.reserve("sample", 1, now=NOW)
    with pytest.raises(LoopLimitReached):
        state.reserve("sample", 1, now=NOW)
    assert state.stopped_reason == "budget_exhausted"
    # A stopped loop refuses every further reservation, not just the kind
    # that tripped it - this is what stops a red-teamed sampled reply from
    # triggering more tool calls once the loop has already been halted.
    with pytest.raises(LoopLimitReached):
        state.reserve("tool", 1, now=NOW)


def test_reserve_stops_on_elapsed_time_even_under_the_counters():
    state = _state(budget=CompanionLoopBudget(tool_calls=100, elapsed_seconds=60))
    with pytest.raises(LoopLimitReached):
        state.reserve("tool", 1, now=NOW + timedelta(seconds=61))
    assert state.stopped_reason == "budget_exhausted"


def test_repeated_failure_stops_the_loop_after_the_threshold():
    state = _state(budget=CompanionLoopBudget(tool_calls=100))
    state.record_failure(NOW)
    state.record_failure(NOW)
    assert state.stopped_reason is None
    state.record_failure(NOW)
    assert state.stopped_reason == "repeated_failure"
    with pytest.raises(LoopLimitReached):
        state.reserve("tool", 1, now=NOW)


def test_a_successful_reservation_resets_the_failure_streak():
    state = _state(budget=CompanionLoopBudget(tool_calls=100))
    state.record_failure(NOW)
    state.record_failure(NOW)
    state.reserve("tool", 1, now=NOW)
    assert state.consecutive_failures == 0


@pytest.mark.parametrize(
    "reason",
    [LoopStopReason.CAPABILITY_LOSS, LoopStopReason.CANCELLED, LoopStopReason.UNRESOLVED_CONSENT],
)
def test_explicit_stop_reasons_halt_the_loop(reason):
    state = _state()
    state.stop(reason, NOW)
    assert state.stopped_reason == reason.value
    with pytest.raises(LoopLimitReached):
        state.reserve("tool", 1, now=NOW)


def test_budget_exhausted_is_not_an_explicit_stop_reason():
    state = _state()
    with pytest.raises(ValueError):
        state.stop(LoopStopReason.BUDGET_EXHAUSTED, NOW)


def test_negative_budgets_are_rejected():
    with pytest.raises(ValueError):
        CompanionLoopBudget(tool_calls=-1)
