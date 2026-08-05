from app.domain.services.spaced_repetition import FSRSScheduler
from app.domain.value_objects import ReviewOutcome, ReviewState


def test_fsrs_schedules_and_reports_retrievability():
    scheduler = FSRSScheduler()
    initial = ReviewState.initial()
    scheduled = scheduler.schedule_next(initial, ReviewOutcome.CORRECT)
    assert scheduled.repetitions == 1
    assert scheduled.interval_days >= 1
    assert 0 < scheduler.retrievability(scheduled) <= 1
