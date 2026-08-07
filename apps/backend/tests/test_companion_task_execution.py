"""Pure domain tests for the #197 TODO 3 execution building blocks."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.companion_task_execution import extract_candidate_terms
from app.domain.services.companion_tasks import CompanionTask, CompanionTaskStatus, CompanionTaskType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_extract_candidate_terms_is_deterministic_bounded_and_deduplicated():
    text = "The cat sat on the mat. The cat! CAT."
    assert extract_candidate_terms(text, max_terms=10) == ["The", "cat", "sat", "mat"]
    assert extract_candidate_terms(text, max_terms=2) == ["The", "cat"]


def test_extract_candidate_terms_rejects_non_positive_bound():
    with pytest.raises(ValueError, match="positive"):
        extract_candidate_terms("hola", 0)


def _task(**overrides):
    values = {
        "id": "task-1",
        "session_id": "session-1",
        "user_id": 1,
        "task_type": CompanionTaskType.EXTRACTION,
        "status": CompanionTaskStatus.RUNNING,
        "total_units": 3,
        "completed_units": 1,
        "result": {"partial": True, "items": ["uno"]},
        "error": None,
        "operation_id": None,
        "expires_at": NOW + timedelta(minutes=5),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return CompanionTask(**values)


def test_record_partial_result_leaves_status_and_progress_untouched():
    task = _task()
    task.record_partial_result({"partial": True, "items": ["uno", "dos"]}, NOW + timedelta(seconds=1))
    assert task.status is CompanionTaskStatus.RUNNING
    assert task.completed_units == 1  # unchanged: this is not progress
    assert task.result == {"partial": True, "items": ["uno", "dos"]}


def test_record_partial_result_works_after_cancellation_but_not_after_completion():
    cancelled = _task()
    cancelled.cancel(NOW + timedelta(seconds=1))
    cancelled.record_partial_result({"partial": True, "items": ["uno"]}, NOW + timedelta(seconds=2))
    assert cancelled.status is CompanionTaskStatus.CANCELLED
    assert cancelled.result == {"partial": True, "items": ["uno"]}

    completed = _task()
    completed.complete({"partial": False, "items": ["uno", "dos", "tres"]}, NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="final"):
        completed.record_partial_result({"partial": True, "items": []}, NOW + timedelta(seconds=2))


def test_task_input_is_bounded():
    with pytest.raises(ValueError, match="8000"):
        _task(input={"candidates": ["x" * 100] * 200})
