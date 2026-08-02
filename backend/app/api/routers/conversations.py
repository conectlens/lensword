"""The conversation tutor (issue #135).

Sending a message always answers HTTP 200 with a `status`, the same way
mnemonic suggestions and learning paths do — a provider switched off or
temporarily down is a normal state of a healthy install.

One thing this router is careful about: **the learner's own turn is stored
before the model is called.** Losing what someone typed because a model was
down is the single outcome that makes a chat feel broken, and it is entirely
avoidable.
"""
import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    ConversationRepo,
    CurrentUser,
    MistakeEventRepo,
    OptionalAIProvider,
)
from app.api.schemas.conversations import (
    ConversationResponse,
    CorrectionResponse,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
    StartConversationRequest,
)
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.conversation import (
    Difficulty,
    Speaker,
    Turn,
    build_context,
    validate_reply,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversation tutor"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def start_conversation(
    payload: StartConversationRequest, current_user: CurrentUser, repo: ConversationRepo
) -> ConversationResponse:
    session = repo.start(
        user_id=current_user.id,
        target_language=payload.target_language,
        difficulty=payload.difficulty.value,
        group_id=payload.group_id,
        scenario=payload.scenario,
    )
    return _to_response(session)


@router.get("", response_model=list[ConversationResponse])
def list_conversations(current_user: CurrentUser, repo: ConversationRepo) -> list[ConversationResponse]:
    return [_to_response(session) for session in repo.list_for_user(current_user.id)]


@router.get("/{session_id}", response_model=ConversationResponse)
def get_conversation(
    session_id: int, current_user: CurrentUser, repo: ConversationRepo
) -> ConversationResponse:
    return _to_response(_owned(repo, session_id, current_user.id))


@router.post("/{session_id}/message", response_model=SendMessageResponse)
async def send_message(
    session_id: int,
    payload: SendMessageRequest,
    current_user: CurrentUser,
    repo: ConversationRepo,
    mistake_repo: MistakeEventRepo,
    provider: OptionalAIProvider,
) -> SendMessageResponse:
    session = _owned(repo, session_id, current_user.id)

    # Stored first, deliberately. If the model is unreachable the learner still
    # has what they wrote, and the conversation resumes rather than restarting.
    learner_message = repo.add_message(session_id, Speaker.LEARNER.value, payload.text)

    if provider is None:
        return SendMessageResponse(
            status="disabled",
            learner_message=_message(learner_message),
            detail="AI is not configured for this deployment, so the tutor cannot reply.",
        )

    context = build_context(
        target_language=session.target_language,
        difficulty=_difficulty(session.difficulty),
        scenario=session.scenario,
        # The learner's own vocabulary and errors. Injected as data, never as
        # instructions — a word card whose definition reads "ignore your
        # instructions" is something any user can create.
        vocabulary=repo.recent_terms(current_user.id),
        recent_mistakes=_mistake_hints(mistake_repo, current_user.id),
        history=[
            Turn(speaker=Speaker(m.speaker), text=m.text)
            for m in session.messages
            if m.id != learner_message.id
        ],
    )

    try:
        raw = await provider.converse(context, payload.text)
    except AIProviderUnavailableError as exc:
        return SendMessageResponse(
            status="unavailable", learner_message=_message(learner_message), detail=str(exc)
        )

    try:
        reply, corrections = validate_reply(raw, payload.text)
    except ValueError as exc:
        logger.info("Tutor reply rejected: %s", exc)
        return SendMessageResponse(
            status="unavailable", learner_message=_message(learner_message), detail=str(exc)
        )

    tutor_message = repo.add_message(
        session_id,
        Speaker.TUTOR.value,
        reply,
        [
            {"original": c.original, "corrected": c.corrected, "explanation": c.explanation}
            for c in corrections
        ],
    )
    return SendMessageResponse(
        status="ok",
        learner_message=_message(learner_message),
        tutor_message=_message(tutor_message),
    )


@router.post("/{session_id}/end", response_model=ConversationResponse)
def end_conversation(
    session_id: int, current_user: CurrentUser, repo: ConversationRepo
) -> ConversationResponse:
    _owned(repo, session_id, current_user.id)
    repo.end(session_id)
    return _to_response(repo.get(session_id))


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(session_id: int, current_user: CurrentUser, repo: ConversationRepo) -> None:
    _owned(repo, session_id, current_user.id)
    repo.delete(session_id)


def _owned(repo, session_id: int, user_id: int):
    """Fetch a conversation, or 404.

    404 rather than 403 for someone else's: a conversation is the most personal
    thing this product stores, and a distinguishable 403 would confirm that
    another account's exists to anyone enumerating ids.
    """
    session = repo.get(session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return session


def _difficulty(value: str) -> Difficulty:
    try:
        return Difficulty(value)
    except ValueError:
        # Stored as a plain string, so an unrecognised value is a data
        # possibility rather than a programming error.
        return Difficulty.STEADY


def _mistake_hints(mistake_repo, user_id: int) -> list[str]:
    """Recent errors, phrased for a prompt.

    Only what the learner actually typed — the category is our label for it,
    and telling a tutor "this learner makes inflection errors" would have it
    teach our taxonomy rather than their language.
    """
    hints = []
    for row in mistake_repo.list_for_user(user_id, limit=40):
        if row.attempted_answer:
            hints.append(row.attempted_answer)
    return hints


def _message(model) -> MessageResponse:
    return MessageResponse(
        id=model.id,
        speaker=model.speaker,
        text=model.text,
        corrections=[CorrectionResponse(**c) for c in (model.corrections or [])],
        created_at=model.created_at,
    )


def _to_response(session) -> ConversationResponse:
    return ConversationResponse(
        id=session.id,
        target_language=session.target_language,
        difficulty=session.difficulty,
        scenario=session.scenario,
        group_id=session.group_id,
        created_at=session.created_at,
        ended_at=session.ended_at,
        messages=[_message(m) for m in sorted(session.messages, key=lambda m: m.id)],
    )
