from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, GroupRepo, RoomRepo, WordRepo
from app.api.mappers import room_summary_to_response, room_to_response, word_to_response
from app.api.schemas.vocabulary import PlaceWordRequest, RoomCreateRequest, RoomResponse, WordResponse
from app.application.use_cases.vocabulary import (
    CreateRoomUseCase,
    DeleteRoomUseCase,
    GetRoomDetailUseCase,
    ListRoomsUseCase,
    PlaceWordUseCase,
    RemovePlacementUseCase,
)
from app.domain.exceptions import EntityNotFoundError, InvalidPlacementError, PermissionDeniedError

router = APIRouter(prefix="/api/v1/rooms", tags=["rooms"])


def _raise_for(exc: Exception):
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, InvalidPlacementError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@router.get("", response_model=list[RoomResponse])
def list_rooms(current_user: CurrentUser, room_repo: RoomRepo, word_repo: WordRepo) -> list[RoomResponse]:
    summaries = ListRoomsUseCase(room_repo, word_repo).execute(current_user.id)
    return [room_summary_to_response(s) for s in summaries]


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(
    payload: RoomCreateRequest, current_user: CurrentUser, room_repo: RoomRepo, group_repo: GroupRepo, word_repo: WordRepo
) -> RoomResponse:
    try:
        room = CreateRoomUseCase(room_repo, group_repo).execute(
            current_user.id, payload.group_id, payload.name, payload.icon
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
    return room_to_response(room, word_repo.count_by_group(room.group_id))


@router.get("/{room_id}", response_model=RoomResponse)
def get_room(
    room_id: int, current_user: CurrentUser, room_repo: RoomRepo, word_repo: WordRepo, group_repo: GroupRepo
) -> RoomResponse:
    try:
        room, _words, _group = GetRoomDetailUseCase(room_repo, word_repo, group_repo).execute(current_user.id, room_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
    return room_to_response(room, word_repo.count_by_group(room.group_id))


@router.get("/{room_id}/words", response_model=list[WordResponse])
def get_room_words(
    room_id: int, current_user: CurrentUser, room_repo: RoomRepo, word_repo: WordRepo, group_repo: GroupRepo
) -> list[WordResponse]:
    """All words belonging to this room's group — placed and unplaced alike
    (the frontend distinguishes using each word's presence in `placements`)."""
    try:
        _room, words, _group = GetRoomDetailUseCase(room_repo, word_repo, group_repo).execute(current_user.id, room_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
    return [word_to_response(w) for w in words]


@router.post("/{room_id}/placements", response_model=RoomResponse)
def place_word(
    room_id: int, payload: PlaceWordRequest, current_user: CurrentUser, room_repo: RoomRepo, word_repo: WordRepo
) -> RoomResponse:
    try:
        room = PlaceWordUseCase(room_repo, word_repo).execute(
            current_user.id, room_id, payload.word_id, payload.x_percent, payload.y_percent
        )
    except (EntityNotFoundError, PermissionDeniedError, InvalidPlacementError) as exc:
        _raise_for(exc)
    return room_to_response(room, word_repo.count_by_group(room.group_id))


@router.delete("/{room_id}/placements/{word_id}", response_model=RoomResponse)
def remove_placement(
    room_id: int, word_id: int, current_user: CurrentUser, room_repo: RoomRepo, word_repo: WordRepo
) -> RoomResponse:
    try:
        room = RemovePlacementUseCase(room_repo).execute(current_user.id, room_id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
    return room_to_response(room, word_repo.count_by_group(room.group_id))


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(room_id: int, current_user: CurrentUser, room_repo: RoomRepo) -> None:
    try:
        DeleteRoomUseCase(room_repo).execute(current_user.id, room_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
