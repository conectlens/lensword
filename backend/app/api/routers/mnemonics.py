from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, MnemonicRepo, OptionalAIProvider, WordRepo
from app.api.mappers import mnemonic_to_response
from app.api.schemas.review import (
    MnemonicCreateRequest,
    MnemonicResponse,
    MnemonicSuggestionDisabled,
    MnemonicSuggestionOk,
    MnemonicSuggestionResponse,
    MnemonicSuggestionUnavailable,
    MnemonicVoteRequest,
)
from app.application.use_cases.review import (
    AddMnemonicUseCase,
    ListMnemonicsUseCase,
    SuggestMnemonicUseCase,
    VoteMnemonicUseCase,
)
from app.domain.exceptions import (
    AIProviderNotConfiguredError,
    AIProviderUnavailableError,
    EntityNotFoundError,
    ValidationError,
)

router = APIRouter(prefix="/api/v1/words/{word_id}/mnemonics", tags=["mnemolab"])


@router.get("", response_model=list[MnemonicResponse])
def list_mnemonics(word_id: int, current_user: CurrentUser, mnemonic_repo: MnemonicRepo) -> list[MnemonicResponse]:
    notes = ListMnemonicsUseCase(mnemonic_repo).execute(word_id)
    return [mnemonic_to_response(n) for n in notes]


@router.post("", response_model=MnemonicResponse, status_code=status.HTTP_201_CREATED)
def add_mnemonic(
    word_id: int, payload: MnemonicCreateRequest, current_user: CurrentUser, mnemonic_repo: MnemonicRepo, word_repo: WordRepo
) -> MnemonicResponse:
    try:
        note = AddMnemonicUseCase(mnemonic_repo, word_repo).execute(current_user.id, word_id, payload.text)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return mnemonic_to_response(note)


@router.post("/suggest", response_model=MnemonicSuggestionResponse)
def suggest_mnemonic(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, ai_provider: OptionalAIProvider
) -> MnemonicSuggestionResponse:
    """Always 200, with the outcome carried in `status`.

    AI is optional and locally hosted, so both "switched off" and "daemon
    isn't running" are ordinary states of a healthy install. Reporting them
    as HTTP errors would make the client treat a configuration choice like a
    fault; the discriminated status keeps the two apart without the client
    having to parse an error message.
    """
    try:
        text = SuggestMnemonicUseCase(word_repo, ai_provider).execute(word_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AIProviderNotConfiguredError:
        return MnemonicSuggestionDisabled()
    except AIProviderUnavailableError as exc:
        return MnemonicSuggestionUnavailable(detail=str(exc))
    return MnemonicSuggestionOk(text=text)


@router.post("/{mnemonic_id}/vote", response_model=MnemonicResponse)
def vote_mnemonic(
    word_id: int, mnemonic_id: int, payload: MnemonicVoteRequest, current_user: CurrentUser, mnemonic_repo: MnemonicRepo
) -> MnemonicResponse:
    try:
        note = VoteMnemonicUseCase(mnemonic_repo).execute(mnemonic_id, payload.upvote)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return mnemonic_to_response(note)
