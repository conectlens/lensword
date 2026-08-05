from datetime import datetime
from pydantic import BaseModel


class WeeklyLearningReportResponse(BaseModel):
    id: int
    snapshot: dict
    narration: str | None
    created_at: datetime
