from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CurrentUser,
    DailySessionPreferenceRepo,
    GroupRepo,
    OptionalAIProvider,
    PracticeExerciseRepo,
    WordRepo,
)
from app.api.schemas.practice import (
    DailySessionRequest,
    DailySessionResponse,
    ExerciseAnswerRequest,
    ExerciseGenerateRequest,
    ExerciseResponse,
    PronunciationFeedbackRequest,
    PronunciationFeedbackResponse,
    WritingCorrectionRequest,
    WritingCorrectionResponse,
)
from app.application.use_cases.practice import (
    AnswerExerciseUseCase,
    GenerateExerciseUseCase,
    GetDailySessionUseCase,
    UpdateDailySessionUseCase,
)
from app.application.use_cases.vocabulary import _require_word_owner
from app.domain.entities import DailySessionPreference
from app.domain.exceptions import AIProviderNotConfiguredError, AIProviderUnavailableError, EntityNotFoundError, PermissionDeniedError

router = APIRouter(prefix="/api/v1/practice", tags=["adaptive practice"])


def _exercise_response(exercise) -> ExerciseResponse:
    return ExerciseResponse(
        id=exercise.id, word_id=exercise.word_id, kind=exercise.kind, prompt=exercise.prompt,
        options=exercise.options, answered=exercise.answered, correct=exercise.correct,
    )


@router.post("/exercises", response_model=ExerciseResponse, status_code=status.HTTP_201_CREATED)
def generate_exercise(
    payload: ExerciseGenerateRequest, current_user: CurrentUser, exercises: PracticeExerciseRepo,
    words: WordRepo, groups: GroupRepo,
) -> ExerciseResponse:
    try:
        word = _require_word_owner(words, groups, payload.word_id, current_user.id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _exercise_response(GenerateExerciseUseCase(exercises, words).execute(current_user.id, word, payload.kind))


@router.post("/exercises/{exercise_id}/answer", response_model=ExerciseResponse)
def answer_exercise(
    exercise_id: int, payload: ExerciseAnswerRequest, current_user: CurrentUser, exercises: PracticeExerciseRepo,
) -> ExerciseResponse:
    try:
        exercise = AnswerExerciseUseCase(exercises).execute(current_user.id, exercise_id, payload.response)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _exercise_response(exercise)


@router.post("/pronunciation-feedback", response_model=PronunciationFeedbackResponse)
def pronunciation_feedback(
    payload: PronunciationFeedbackRequest, current_user: CurrentUser, words: WordRepo, groups: GroupRepo,
) -> PronunciationFeedbackResponse:
    """A transcript-containment check, not acoustic pronunciation scoring
    (issue #198 TODO 2). `transcript` is text — speech-to-text output the
    caller already produced — not audio; nothing here measures how a word
    sounded, only whether the target term appears in what was heard. The
    frontend's own copy already states this plainly to the learner
    (PronunciationPractice.tsx); this docstring exists so a caller reading
    only this endpoint's name (an MCP tool description, API docs, or any
    future companion surface) doesn't infer real acoustic measurement that
    isn't there. A genuine speech/pronunciation adapter would be a new,
    separate capability behind its own interface, not a change to this one.
    """
    try:
        word = _require_word_owner(words, groups, payload.word_id, current_user.id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    accepted = word.term.casefold() in payload.transcript.casefold() or payload.transcript.casefold() in word.term.casefold()
    feedback = "Great match—your transcript contains the target word." if accepted else f"Try again and aim for '{word.term}'."
    return PronunciationFeedbackResponse(accepted=accepted, feedback=feedback)


@router.post("/writing-correction", response_model=WritingCorrectionResponse)
async def writing_correction(
    payload: WritingCorrectionRequest, current_user: CurrentUser, words: WordRepo, groups: GroupRepo, provider: OptionalAIProvider,
) -> WritingCorrectionResponse:
    try:
        word = _require_word_owner(words, groups, payload.word_id, current_user.id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(AIProviderNotConfiguredError()))
    try:
        feedback = await provider.generate_field("writing_correction", word.term, None, word.target_language.value, payload.text)
    except AIProviderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return WritingCorrectionResponse(corrected_text=payload.text, feedback=feedback or "Writing received; compare it with the target word and try again.")


@router.get("/daily-session", response_model=DailySessionResponse)
def get_daily_session(current_user: CurrentUser, preferences: DailySessionPreferenceRepo, words: WordRepo) -> DailySessionResponse:
    preference, due_count = GetDailySessionUseCase(preferences, words).execute(current_user.id)
    return DailySessionResponse(**asdict(preference), due_count=due_count)


@router.put("/daily-session", response_model=DailySessionResponse)
def update_daily_session(
    payload: DailySessionRequest, current_user: CurrentUser, preferences: DailySessionPreferenceRepo, words: WordRepo,
) -> DailySessionResponse:
    preference = UpdateDailySessionUseCase(preferences).execute(DailySessionPreference(user_id=current_user.id, **payload.model_dump()))
    _, due_count = GetDailySessionUseCase(preferences, words).execute(current_user.id)
    return DailySessionResponse(**asdict(preference), due_count=due_count)
