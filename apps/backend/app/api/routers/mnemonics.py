from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, GroupRepo, MnemonicRepo, OptionalAIProvider, WordRepo
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
    PermissionDeniedError,
    ValidationError,
)

router = APIRouter(prefix="/api/v1/words/{word_id}/mnemonics", tags=["mnemolab"])


def _handle_common_errors(exc: Exception):
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    raise exc


@router.get("", response_model=list[MnemonicResponse])
def list_mnemonics(
    word_id: int, current_user: CurrentUser, mnemonic_repo: MnemonicRepo, word_repo: WordRepo, group_repo: GroupRepo
) -> list[MnemonicResponse]:
    try:
        notes = ListMnemonicsUseCase(mnemonic_repo, word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return [mnemonic_to_response(n) for n in notes]


@router.post("", response_model=MnemonicResponse, status_code=status.HTTP_201_CREATED)
def add_mnemonic(
    word_id: int,
    payload: MnemonicCreateRequest,
    current_user: CurrentUser,
    mnemonic_repo: MnemonicRepo,
    word_repo: WordRepo,
    group_repo: GroupRepo,
) -> MnemonicResponse:
    try:
        note = AddMnemonicUseCase(mnemonic_repo, word_repo, group_repo).execute(
            current_user.id, word_id, payload.text
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return mnemonic_to_response(note)


@router.post("/suggest", response_model=MnemonicSuggestionResponse)
async def suggest_mnemonic(
    word_id: int,
    current_user: CurrentUser,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    ai_provider: OptionalAIProvider,
    db: DbSession,
) -> MnemonicSuggestionResponse:
    """Always 200, with the outcome carried in `status`.

    AI is optional and locally hosted, so both "switched off" and "daemon
    isn't running" are ordinary states of a healthy install. Reporting them
    as HTTP errors would make the client treat a configuration choice like a
    fault; the discriminated status keeps the two apart without the client
    having to parse an error message.

    `async def` so that a slow generation waits on the event loop rather than
    occupying one of the server's bounded worker threads, where a handful of
    hung calls would make unrelated endpoints unresponsive.
    """
    use_case = SuggestMnemonicUseCase(word_repo, group_repo, ai_provider)
    try:
        word = use_case.resolve_word(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)

    # Hand the pooled database connection back before waiting on the model.
    # get_db otherwise holds it for the whole request, and the engine pool is
    # far smaller than the number of requests a hung provider can pile up —
    # so without this, slow generations starve every other endpoint of
    # connections even though no worker thread is blocked. `word` is a
    # detached domain object and stays valid.
    db.close()

    try:
        text = await use_case.generate(word)
    except AIProviderNotConfiguredError:
        return MnemonicSuggestionDisabled()
    except AIProviderUnavailableError as exc:
        return MnemonicSuggestionUnavailable(detail=str(exc))
    return MnemonicSuggestionOk(text=text)


@router.post("/{mnemonic_id}/vote", response_model=MnemonicResponse)
def vote_mnemonic(
    word_id: int,
    mnemonic_id: int,
    payload: MnemonicVoteRequest,
    current_user: CurrentUser,
    mnemonic_repo: MnemonicRepo,
    word_repo: WordRepo,
    group_repo: GroupRepo,
) -> MnemonicResponse:
    try:
        note = VoteMnemonicUseCase(mnemonic_repo, word_repo, group_repo).execute(
            current_user.id, word_id, mnemonic_id, payload.upvote
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return mnemonic_to_response(note)
