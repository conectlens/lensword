from collections import Counter
from datetime import datetime, timedelta, timezone

from app.domain.entities import WeeklyLearningReport
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import ReviewSessionRepository, WeeklyLearningReportRepository, WordRepository
from app.domain.value_objects import ReviewOutcome, zone_for


class BuildWeeklyLearningReportUseCase:
    def __init__(self, sessions: ReviewSessionRepository, words: WordRepository, reports: WeeklyLearningReportRepository):
        self.sessions, self.words, self.reports = sessions, words, reports

    def execute(self, user_id: int, time_zone: str) -> WeeklyLearningReport:
        now = datetime.now(timezone.utc)
        local_now = now.astimezone(zone_for(time_zone))
        local_start = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        end = (local_start + timedelta(days=7)).astimezone(timezone.utc).replace(tzinfo=None)
        sessions = [session for session in self.sessions.list_recent_by_user(user_id, start) if session.started_at < end]
        attempts = [attempt for session in sessions for attempt in session.attempts if start <= attempt.answered_at < end]
        incorrect = [attempt for attempt in attempts if attempt.outcome != ReviewOutcome.CORRECT]
        categories: Counter[str] = Counter()
        for attempt in incorrect:
            word = self.words.get_by_id(attempt.word_id)
            if word and word.category:
                categories[word.category] += 1
        by_hour: Counter[str] = Counter(attempt.answered_at.replace(tzinfo=timezone.utc).astimezone(zone_for(time_zone)).strftime("%H:00") for attempt in attempts)
        due_now = len(self.words.list_due_for_user(user_id, limit=1000))
        snapshot = {
            "schema_version": 1,
            "week": {"start": start.isoformat(), "end": end.isoformat(), "time_zone": time_zone},
            "source_range": {"session_count": len(sessions), "attempt_count": len(attempts)},
            "studied": len(attempts),
            "retained": sum(attempt.outcome == ReviewOutcome.CORRECT for attempt in attempts),
            "overdue": due_now,
            "difficult_topics": [{"name": name, "mistakes": count} for name, count in categories.most_common(5)],
            "repeated_mistake_categories": [{"name": name, "mistakes": count} for name, count in categories.most_common(5)],
            "productive_time_windows": [{"label": label, "attempts": count} for label, count in by_hour.most_common(3)],
            "data_completeness": {"status": "complete" if attempts else "sparse", "warnings": [] if attempts else ["No review attempts were recorded for this week."], "missing_data": [] if attempts else ["review_attempts"]},
            "generated_at": now.replace(tzinfo=None).isoformat(),
        }
        return self.reports.add(WeeklyLearningReport(id=None, user_id=user_id, week_start=start, week_end=end, time_zone=time_zone, snapshot=snapshot))


class GetWeeklyLearningReportUseCase:
    def __init__(self, reports: WeeklyLearningReportRepository): self.reports = reports
    def execute(self, user_id: int, report_id: int) -> WeeklyLearningReport:
        report = self.reports.get_by_id(report_id)
        if report is None: raise EntityNotFoundError("WeeklyLearningReport", report_id)
        if report.user_id != user_id: raise PermissionDeniedError("This report belongs to another account")
        return report
