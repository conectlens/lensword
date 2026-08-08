from fastapi import APIRouter, HTTPException, status
import json
from app.api.deps import CurrentUser, PerUserAIProvider, ReviewSessionRepo, WeeklyLearningReportRepo, WordRepo
from app.api.schemas.reports import WeeklyLearningReportResponse
from app.application.use_cases.reports import BuildWeeklyLearningReportUseCase, GetWeeklyLearningReportUseCase
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.exceptions import AIProviderUnavailableError

router = APIRouter(prefix="/api/v1/reports", tags=["learning reports"])

def _response(report) -> WeeklyLearningReportResponse:
    return WeeklyLearningReportResponse(id=report.id, snapshot=report.snapshot, narration=report.narration, created_at=report.created_at)

@router.post("/weekly", response_model=WeeklyLearningReportResponse, status_code=status.HTTP_201_CREATED)
def build_weekly_report(current_user: CurrentUser, sessions: ReviewSessionRepo, words: WordRepo, reports: WeeklyLearningReportRepo) -> WeeklyLearningReportResponse:
    return _response(BuildWeeklyLearningReportUseCase(sessions, words, reports).execute(current_user.id, current_user.time_zone))

@router.get("/weekly", response_model=list[WeeklyLearningReportResponse])
def list_weekly_reports(current_user: CurrentUser, reports: WeeklyLearningReportRepo) -> list[WeeklyLearningReportResponse]:
    return [_response(report) for report in reports.list_by_user(current_user.id)]

@router.get("/weekly/{report_id}", response_model=WeeklyLearningReportResponse)
def get_weekly_report(report_id: int, current_user: CurrentUser, reports: WeeklyLearningReportRepo) -> WeeklyLearningReportResponse:
    try: return _response(GetWeeklyLearningReportUseCase(reports).execute(current_user.id, report_id))
    except EntityNotFoundError as exc: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

@router.post("/weekly/{report_id}/narration", response_model=WeeklyLearningReportResponse)
async def generate_narration(report_id: int, current_user: CurrentUser, reports: WeeklyLearningReportRepo, provider: PerUserAIProvider) -> WeeklyLearningReportResponse:
    try: report = GetWeeklyLearningReportUseCase(reports).execute(current_user.id, report_id)
    except EntityNotFoundError as exc: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if provider is None: return _response(report)
    try: report.narration = await provider.generate_field("weekly_report", "weekly report", None, "English", json.dumps(report.snapshot, sort_keys=True))
    except AIProviderUnavailableError: return _response(report)
    return _response(reports.update(report))
