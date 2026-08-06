from pydantic import BaseModel, Field


class ExerciseGenerateRequest(BaseModel):
    word_id: int
    kind: str = Field(default="translation", pattern="^(translation|definition|cloze)$")


class ExerciseResponse(BaseModel):
    id: int
    word_id: int
    kind: str
    prompt: str
    options: list[str]
    answered: bool
    correct: bool | None


class ExerciseAnswerRequest(BaseModel):
    response: str = Field(min_length=1, max_length=1000)


class PronunciationFeedbackRequest(BaseModel):
    # Speech-to-text output the caller already produced, not audio — this
    # checks whether the target term appears in it, nothing acoustic
    # (issue #198 TODO 2; see the router's docstring for the full context).
    word_id: int
    transcript: str = Field(min_length=1, max_length=500)


class PronunciationFeedbackResponse(BaseModel):
    accepted: bool
    feedback: str


class WritingCorrectionRequest(BaseModel):
    word_id: int
    text: str = Field(min_length=1, max_length=2000)


class WritingCorrectionResponse(BaseModel):
    corrected_text: str
    feedback: str


class DailySessionRequest(BaseModel):
    enabled: bool = True
    goal_minutes: int = Field(default=10, ge=1, le=180)
    review_limit: int = Field(default=20, ge=1, le=100)


class DailySessionResponse(DailySessionRequest):
    due_count: int = 0
