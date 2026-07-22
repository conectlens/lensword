from dataclasses import dataclass
from datetime import datetime

from app.domain.entities import Group, Room, Word
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import GroupRepository, RoomRepository, WordRepository
from app.domain.value_objects import SupportedLanguage


def _require_group_owner(group_repo: GroupRepository, group_id: int, owner_id: int) -> Group:
    group = group_repo.get_by_id(group_id)
    if group is None:
        raise EntityNotFoundError("Group", group_id)
    if group.owner_id != owner_id:
        raise PermissionDeniedError("This group belongs to another account")
    return group


def _require_word_owner(word_repo: WordRepository, group_repo: GroupRepository, word_id: int, owner_id: int) -> Word:
    word = word_repo.get_by_id(word_id)
    if word is None:
        raise EntityNotFoundError("Word", word_id)
    _require_group_owner(group_repo, word.group_id, owner_id)
    return word


def _require_room_owner(room_repo: RoomRepository, room_id: int, owner_id: int) -> Room:
    room = room_repo.get_by_id(room_id)
    if room is None:
        raise EntityNotFoundError("Room", room_id)
    if room.owner_id != owner_id:
        raise PermissionDeniedError("This room belongs to another account")
    return room


@dataclass(frozen=True, slots=True)
class GroupSummary:
    group: Group
    word_count: int
    mastered_count: int
    due_count: int
    last_reviewed_at: datetime | None


class CreateGroupUseCase:
    def __init__(self, group_repo: GroupRepository):
        self.group_repo = group_repo

    def execute(self, owner_id: int, name: str, target_language: SupportedLanguage) -> Group:
        group = Group(id=None, owner_id=owner_id, name=name.strip(), target_language=target_language)
        return self.group_repo.add(group)


class ListGroupsUseCase:
    def __init__(self, group_repo: GroupRepository, word_repo: WordRepository):
        self.group_repo = group_repo
        self.word_repo = word_repo

    def execute(self, owner_id: int) -> list[GroupSummary]:
        summaries = []
        for group in self.group_repo.list_by_owner(owner_id):
            words = self.word_repo.list_by_group(group.id)  # type: ignore[arg-type]
            mastered = sum(1 for w in words if w.review_state.strength >= 80)
            due = sum(1 for w in words if w.is_due)
            last_reviewed = max(
                (w.review_state.last_reviewed_at for w in words if w.review_state.last_reviewed_at), default=None
            )
            summaries.append(
                GroupSummary(
                    group=group, word_count=len(words), mastered_count=mastered, due_count=due,
                    last_reviewed_at=last_reviewed,
                )
            )
        return summaries


class GetGroupDetailUseCase:
    def __init__(self, group_repo: GroupRepository, word_repo: WordRepository):
        self.group_repo = group_repo
        self.word_repo = word_repo

    def execute(self, owner_id: int, group_id: int) -> tuple[Group, list[Word]]:
        group = _require_group_owner(self.group_repo, group_id, owner_id)
        words = self.word_repo.list_by_group(group_id)
        return group, words


class RenameGroupUseCase:
    def __init__(self, group_repo: GroupRepository):
        self.group_repo = group_repo

    def execute(self, owner_id: int, group_id: int, new_name: str) -> Group:
        group = _require_group_owner(self.group_repo, group_id, owner_id)
        group.rename(new_name)
        return self.group_repo.update(group)


class DeleteGroupUseCase:
    def __init__(self, group_repo: GroupRepository):
        self.group_repo = group_repo

    def execute(self, owner_id: int, group_id: int) -> None:
        _require_group_owner(self.group_repo, group_id, owner_id)
        self.group_repo.delete(group_id)


@dataclass(frozen=True, slots=True)
class WordInput:
    term: str
    target_language: SupportedLanguage
    translations: list[str]
    example_sentence: str | None = None
    mnemonic: str | None = None
    category: str | None = None


class AddWordUseCase:
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, group_id: int, data: WordInput) -> Word:
        _require_group_owner(self.group_repo, group_id, owner_id)
        word = Word(
            id=None,
            group_id=group_id,
            term=data.term.strip(),
            target_language=data.target_language,
            example_sentence=data.example_sentence,
            category=data.category,
        )
        for t in data.translations:
            word.add_translation(t)
        word.set_mnemonic(data.mnemonic)
        return self.word_repo.add(word)


class UpdateWordUseCase:
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int, data: WordInput) -> Word:
        word = _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        word.term = data.term.strip()
        word.target_language = data.target_language
        word.translations = []
        for t in data.translations:
            word.add_translation(t)
        word.example_sentence = data.example_sentence
        word.set_mnemonic(data.mnemonic)
        word.category = data.category
        return self.word_repo.update(word)


class DeleteWordUseCase:
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int) -> None:
        _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        self.word_repo.delete(word_id)


class UpdateWordAssociationsUseCase:
    """Add/remove synonyms, antonyms, and topics — powers the mind-map page."""

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(
        self,
        owner_id: int,
        word_id: int,
        add: list[tuple[str, str]] | None = None,
        remove: list[tuple[str, str]] | None = None,
    ) -> Word:
        word = _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        for kind, value in add or []:
            word.add_association(kind, value)
        for kind, value in remove or []:
            word.remove_association(kind, value)
        return self.word_repo.update(word)


class GetWordUseCase:
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int) -> Word:
        return _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)


# --- Rooms (memory palace) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoomSummary:
    room: Room
    group_word_count: int


class CreateRoomUseCase:
    def __init__(self, room_repo: RoomRepository, group_repo: GroupRepository):
        self.room_repo = room_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, group_id: int, name: str, icon: str) -> Room:
        _require_group_owner(self.group_repo, group_id, owner_id)
        room = Room(id=None, owner_id=owner_id, group_id=group_id, name=name.strip(), icon=icon)
        return self.room_repo.add(room)


class ListRoomsUseCase:
    def __init__(self, room_repo: RoomRepository, word_repo: WordRepository):
        self.room_repo = room_repo
        self.word_repo = word_repo

    def execute(self, owner_id: int) -> list[RoomSummary]:
        rooms = self.room_repo.list_by_owner(owner_id)
        return [
            RoomSummary(room=room, group_word_count=self.word_repo.count_by_group(room.group_id)) for room in rooms
        ]


class GetRoomDetailUseCase:
    def __init__(self, room_repo: RoomRepository, word_repo: WordRepository, group_repo: GroupRepository):
        self.room_repo = room_repo
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, room_id: int) -> tuple[Room, list[Word], Group]:
        room = _require_room_owner(self.room_repo, room_id, owner_id)
        words = self.word_repo.list_by_group(room.group_id)
        group = self.group_repo.get_by_id(room.group_id)
        assert group is not None
        return room, words, group


class PlaceWordUseCase:
    def __init__(self, room_repo: RoomRepository, word_repo: WordRepository):
        self.room_repo = room_repo
        self.word_repo = word_repo

    def execute(self, owner_id: int, room_id: int, word_id: int, x_percent: float, y_percent: float) -> Room:
        room = _require_room_owner(self.room_repo, room_id, owner_id)
        word = self.word_repo.get_by_id(word_id)
        if word is None:
            raise EntityNotFoundError("Word", word_id)
        room.place_word(word, x_percent, y_percent)
        return self.room_repo.update(room)


class RemovePlacementUseCase:
    def __init__(self, room_repo: RoomRepository):
        self.room_repo = room_repo

    def execute(self, owner_id: int, room_id: int, word_id: int) -> Room:
        room = _require_room_owner(self.room_repo, room_id, owner_id)
        room.remove_placement(word_id)
        return self.room_repo.update(room)


class DeleteRoomUseCase:
    def __init__(self, room_repo: RoomRepository):
        self.room_repo = room_repo

    def execute(self, owner_id: int, room_id: int) -> None:
        _require_room_owner(self.room_repo, room_id, owner_id)
        self.room_repo.delete(room_id)
