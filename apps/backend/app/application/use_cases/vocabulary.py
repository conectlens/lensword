from dataclasses import dataclass
from datetime import datetime

from app.application.use_cases.knowledge_graph import RecomputeKnowledgeEdgesForWordUseCase
from app.domain.entities import Group, Room, Word
from app.domain.exceptions import (
    EntityNotFoundError,
    InvalidPlacementError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.repositories import GroupRepository, RoomRepository, WordRepository
from app.domain.services.ai_provenance import (
    AI_AUTHORED_FIELDS,
    EditSource,
    changed_fields,
    verification_survives,
)
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


def _invalidate_language_profile(owner_id: int) -> None:
    """Drop this learner's cached language profile (issue #342).

    Called by the use cases that change what the profile is derived from —
    the code performing a mutation is the only place that reliably knows a
    mutation happened, which is why the cache does not try to infer it from
    unrelated signals.

    Imported inside the function on purpose: `mcp_dev_workflow` imports the
    ownership helpers from this module, so a module-level import here would
    close that cycle. The call is a dict `pop`, so the cost of doing the
    lookup per mutation is not worth restructuring two modules to avoid.
    """
    from app.application.use_cases.mcp_dev_workflow import LANGUAGE_PROFILE_CACHE

    LANGUAGE_PROFILE_CACHE.invalidate(owner_id)


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
        created = self.group_repo.add(group)
        _invalidate_language_profile(owner_id)
        return created


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


class UpdateGroupUseCase:
    """Group-level attribute changes: name, target language, or both (#337).

    `None` means "leave this alone" rather than "clear it", so a caller that
    only ever sent a name keeps the behavior it always had.
    """

    def __init__(self, group_repo: GroupRepository):
        self.group_repo = group_repo

    def execute(
        self,
        owner_id: int,
        group_id: int,
        new_name: str | None = None,
        target_language: SupportedLanguage | None = None,
    ) -> Group:
        group = _require_group_owner(self.group_repo, group_id, owner_id)

        if new_name is not None:
            group.rename(new_name)

        language_changed = target_language is not None and target_language != group.target_language
        if language_changed:
            group.retarget(target_language)

        updated = self.group_repo.update(group)

        # Only a language change: the cached profile is derived from which
        # languages this learner studies, so renaming "Spanish 1" to
        # "Spanish Verbs" cannot alter it, and dropping the cache for that
        # would be work with no effect to justify it.
        if language_changed:
            _invalidate_language_profile(owner_id)
        return updated


class DeleteGroupUseCase:
    def __init__(self, group_repo: GroupRepository):
        self.group_repo = group_repo

    def execute(self, owner_id: int, group_id: int) -> None:
        _require_group_owner(self.group_repo, group_id, owner_id)
        self.group_repo.delete(group_id)
        _invalidate_language_profile(owner_id)


@dataclass(frozen=True, slots=True)
class WordInput:
    term: str
    target_language: SupportedLanguage
    translations: list[str]
    example_sentence: str | None = None
    mnemonic: str | None = None
    category: str | None = None
    definition: str | None = None
    part_of_speech: str | None = None
    cefr_level: str | None = None
    pronunciation: str | None = None
    collocations: list[str] | None = None
    tags: list[str] | None = None
    synonyms: list[str] | None = None
    antonyms: list[str] | None = None
    topics: list[str] | None = None
    ai_confidence: float | None = None
    ai_provider: str | None = None
    ai_model: str | None = None


class AddWordUseCase:
    def __init__(
        self,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        edge_repo=None,
        mistake_repo=None,
    ):
        self.word_repo = word_repo
        self.group_repo = group_repo
        # Optional so every existing caller and test that only cares about
        # adding a word is unaffected — the same pattern review.py already
        # uses for mistake_repo.
        self.edge_repo = edge_repo
        self.mistake_repo = mistake_repo

    def execute(self, owner_id: int, group_id: int, data: WordInput) -> Word:
        _require_group_owner(self.group_repo, group_id, owner_id)
        return self._create(owner_id, group_id, data)

    def _create(self, owner_id: int, group_id: int, data: WordInput) -> Word:
        """Build and persist one word, ownership already established.

        Split from `execute` so `AddWordsUseCase` can check the group once
        for a whole batch and still construct every word through exactly this
        code path — a second copy of this constructor would be free to drift
        from it silently.
        """
        word = Word(
            id=None,
            group_id=group_id,
            term=data.term.strip(),
            target_language=data.target_language,
            example_sentence=data.example_sentence,
            category=data.category,
            definition=data.definition,
            part_of_speech=data.part_of_speech,
            cefr_level=data.cefr_level,
            pronunciation=data.pronunciation,
            collocations=list(data.collocations or []),
            tags=list(data.tags or []),
            synonyms=list(data.synonyms or []),
            antonyms=list(data.antonyms or []),
            topics=list(data.topics or []),
            ai_confidence=data.ai_confidence,
            ai_provider=data.ai_provider,
            ai_model=data.ai_model,
        )
        for t in data.translations:
            word.add_translation(t)
        word.set_mnemonic(data.mnemonic)
        added = self.word_repo.add(word)
        self._recompute_edges(owner_id, added.id)
        _invalidate_language_profile(owner_id)
        return added

    def _recompute_edges(self, owner_id: int, word_id: int | None) -> None:
        if self.edge_repo is None or word_id is None:
            return
        RecomputeKnowledgeEdgesForWordUseCase(self.word_repo, self.edge_repo, self.mistake_repo).execute(
            owner_id, word_id
        )


@dataclass(frozen=True, slots=True)
class SkippedWordInput:
    """One item an add batch declined, identified by position.

    Position rather than term: terms are caller-supplied and need not be
    unique within a batch, so an index is the only thing that unambiguously
    points at the item that failed.
    """

    index: int
    reason: str


@dataclass(frozen=True, slots=True)
class AddWordsResult:
    added: tuple[Word, ...]
    skipped: tuple[SkippedWordInput, ...]


class AddWordsUseCase:
    """Add several words to one group, checking that group's ownership once.

    Every word in the batch lands in the same group, so the ownership check
    is a property of the call rather than of each item — N calls to
    `AddWordUseCase` re-answered an identical question N times. Word rows are
    still distinct inserts; unlike batched room placement there is no shared
    aggregate to collapse, so the win here is round trips and repeated
    authorization work rather than write amplification.

    Partial success matches the rest of the batch surface: an item the domain
    rejects is reported with its position, and the valid items around it
    still land.
    """

    def __init__(
        self,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        edge_repo=None,
        mistake_repo=None,
    ):
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.edge_repo = edge_repo
        self.mistake_repo = mistake_repo

    def execute(self, owner_id: int, group_id: int, items: list[WordInput]) -> AddWordsResult:
        _require_group_owner(self.group_repo, group_id, owner_id)
        single = AddWordUseCase(self.word_repo, self.group_repo, self.edge_repo, self.mistake_repo)

        added: list[Word] = []
        skipped: list[SkippedWordInput] = []
        for index, data in enumerate(items):
            try:
                added.append(single._create(owner_id, group_id, data))
            except ValidationError as error:
                # A term the domain refuses (blank after stripping, say) is a
                # property of that item, not of the batch.
                skipped.append(SkippedWordInput(index, str(error) or "invalid_word"))
        return AddWordsResult(added=tuple(added), skipped=tuple(skipped))


_GRAPH_FIELDS = frozenset({"synonyms", "antonyms", "collocations", "topics"})


class UpdateWordUseCase:
    def __init__(
        self,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        revision_repo=None,
        edge_repo=None,
        mistake_repo=None,
    ):
        self.word_repo = word_repo
        self.group_repo = group_repo
        # Optional so callers that do not care about provenance are unaffected.
        # Recording history is bookkeeping beside the edit, not part of it.
        self.revision_repo = revision_repo
        self.edge_repo = edge_repo
        self.mistake_repo = mistake_repo

    def execute(
        self, owner_id: int, word_id: int, data: WordInput, source: EditSource = EditSource.HUMAN
    ) -> Word:
        word = _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        before = _tracked_snapshot(word)
        word.term = data.term.strip()
        word.target_language = data.target_language
        word.translations = []
        for t in data.translations:
            word.add_translation(t)
        word.example_sentence = data.example_sentence
        word.set_mnemonic(data.mnemonic)
        word.category = data.category
        if data.definition is not None: word.definition = data.definition
        if data.part_of_speech is not None: word.part_of_speech = data.part_of_speech
        if data.cefr_level is not None: word.cefr_level = data.cefr_level
        if data.pronunciation is not None: word.pronunciation = data.pronunciation
        if data.collocations is not None: word.collocations = list(data.collocations)
        if data.tags is not None: word.tags = list(data.tags)
        if data.synonyms is not None: word.synonyms = list(data.synonyms)
        if data.antonyms is not None: word.antonyms = list(data.antonyms)
        if data.topics is not None: word.topics = list(data.topics)
        if data.ai_confidence is not None: word.ai_confidence = data.ai_confidence
        if data.ai_provider is not None: word.ai_provider = data.ai_provider
        if data.ai_model is not None: word.ai_model = data.ai_model

        changes = changed_fields(before, _tracked_snapshot(word))
        # A model rewriting a verified field ends the verification: the badge
        # says a person read this text, and after re-enrichment that is no
        # longer true of what is on screen.
        if word.ai_verified_at is not None and not verification_survives(changes, source):
            word.ai_verified_at = None

        updated = self.word_repo.update(word)
        self._record(word_id, before, _tracked_snapshot(word), changes, source)
        if self.edge_repo is not None and _GRAPH_FIELDS.intersection(changes):
            # Only when a field the graph actually derives edges from
            # changed — an edit to example_sentence or mnemonic has no
            # graph consequence and should not touch knowledge_edges.
            RecomputeKnowledgeEdgesForWordUseCase(self.word_repo, self.edge_repo, self.mistake_repo).execute(
                owner_id, word_id
            )
        return updated

    def _record(self, word_id: int, before: dict, after: dict, changes: list[str], source: EditSource) -> None:
        if self.revision_repo is None:
            return
        for field_name in changes:
            self.revision_repo.record(
                word_id=word_id,
                field=field_name,
                before_value=_as_text(before.get(field_name)),
                after_value=_as_text(after.get(field_name)),
                source=source.value,
            )


def _tracked_snapshot(word: Word) -> dict:
    """The AI-authored fields as they stand, for before/after comparison."""
    return {name: getattr(word, name, None) for name in AI_AUTHORED_FIELDS}


def _as_text(value) -> str | None:
    """Flatten a field value for the history.

    Lists are joined on newline rather than stored as JSON: nobody diffs a
    synonym list programmatically, they read it, and text stays legible to
    anyone inspecting the table by hand.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(str(item) for item in value) or None
    text = str(value).strip()
    return text or None


class DeleteWordUseCase:
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int) -> None:
        _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
        self.word_repo.delete(word_id)
        _invalidate_language_profile(owner_id)


class UpdateWordAssociationsUseCase:
    """Add/remove synonyms, antonyms, and topics — powers the mind-map page."""

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository, edge_repo=None, mistake_repo=None):
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.edge_repo = edge_repo
        self.mistake_repo = mistake_repo

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
        updated = self.word_repo.update(word)
        if self.edge_repo is not None and (add or remove):
            RecomputeKnowledgeEdgesForWordUseCase(self.word_repo, self.edge_repo, self.mistake_repo).execute(
                owner_id, word_id
            )
        return updated


class GetWordUseCase:
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, word_id: int) -> Word:
        return _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)


@dataclass(frozen=True, slots=True)
class BulkFieldEdit:
    """The fields a bulk edit may set. `None` means "leave alone".

    Deliberately the same narrow set the REST schema allows: term and
    translations are excluded because they are what makes a card that card,
    and a bulk control able to overwrite forty terms with one value is a
    mistake waiting to be made irreversibly.
    """

    cefr_level: str | None = None
    part_of_speech: str | None = None
    category: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True, slots=True)
class BulkEditResult:
    updated: int
    skipped: tuple[int, ...]


class BulkEditWordsUseCase:
    """Set the same fields on several cards at once.

    Lifted out of the `PATCH /api/v1/words/bulk` route body (issue #347) so
    the MCP tool exposing this capability and the REST route behind the web
    UI run the *same* code rather than two implementations that agree until
    one of them is edited. Words that are not this account's are skipped and
    reported rather than failing the whole request.
    """

    # Only the AI-authored fields carry history; category and tags are
    # organisational and were never model claims about the language.
    _VERSIONED_FIELDS = frozenset({"cefr_level", "part_of_speech"})
    _FIELDS = ("cefr_level", "part_of_speech", "category", "tags")

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository, revision_repo=None):
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.revision_repo = revision_repo

    def execute(self, owner_id: int, word_ids: list[int], edit: BulkFieldEdit) -> BulkEditResult:
        updated = 0
        skipped: list[int] = []
        for word_id in word_ids:
            try:
                word = _require_word_owner(self.word_repo, self.group_repo, word_id, owner_id)
            except (EntityNotFoundError, PermissionDeniedError):
                skipped.append(word_id)
                continue
            if self._apply(word, edit):
                self.word_repo.update(word)
                updated += 1
        return BulkEditResult(updated=updated, skipped=tuple(skipped))

    def _apply(self, word: Word, edit: BulkFieldEdit) -> bool:
        """Apply the set fields, recording each real change. Returns whether any."""
        changed = False
        for name in self._FIELDS:
            new_value = getattr(edit, name)
            # None means "leave alone", which is different from setting a
            # field to empty — an edit that omitted a field must not clear it.
            if new_value is None:
                continue
            old_value = getattr(word, name)
            if old_value == new_value:
                continue
            setattr(word, name, new_value)
            changed = True
            if name in self._VERSIONED_FIELDS and self.revision_repo is not None:
                self.revision_repo.record(
                    word_id=word.id,
                    field=name,
                    before_value=old_value,
                    after_value=new_value,
                    source=EditSource.BULK.value,
                )
        return changed


class SearchWordsUseCase:
    """Search only words inside groups owned by the requesting learner."""
    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo, self.group_repo = word_repo, group_repo

    def execute(self, owner_id: int, query: str, limit: int, offset: int = 0) -> list[Word]:
        needle, matches, skipped = query.strip().casefold(), [], 0
        for group in self.group_repo.list_by_owner(owner_id):
            for word in self.word_repo.list_by_group(group.id or 0):
                if not needle or needle in word.term.casefold() or any(needle in value.casefold() for value in word.translations):
                    if skipped < offset:
                        skipped += 1
                        continue
                    matches.append(word)
                    if len(matches) >= limit:
                        return matches
        return matches


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


@dataclass(frozen=True, slots=True)
class PlacementInput:
    word_id: int
    x_percent: float
    y_percent: float


@dataclass(frozen=True, slots=True)
class SkippedPlacement:
    """One placement the batch declined, and why.

    Reported rather than silently dropped, for the same reason
    `BulkWordEditResponse.skipped` is: a batch that quietly did less than it
    was asked is worse than one that says so.
    """

    word_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class PlaceWordsResult:
    room: Room
    applied: tuple[int, ...]
    skipped: tuple[SkippedPlacement, ...]


class PlaceWordsUseCase:
    """Place many words into one room, loading and saving the aggregate once.

    `PlaceWordUseCase` above is correct for a single placement but is the
    wrong shape for a set of them: called N times against the same room it
    performs N ownership checks, N loads and N writes of *the same* Room, and
    leaves N windows in which a concurrent placement can be lost. The Room is
    the natural transaction boundary for a set of placements, so this reads
    it once, applies every placement to that one loaded aggregate, and
    persists once.

    Word resolution follows the same principle: the room's group is listed
    once rather than fetched per word. Because `Room.place_word` already
    requires a word to belong to the room's own group, that single list is
    exactly the set of placeable words — and because the room's ownership was
    checked first, membership of it is itself proof of ownership. No word
    from another account can reach `place_word` by this path.

    Partial success is deliberate: an invalid word id midway through must not
    discard the valid placements that preceded it.
    """

    def __init__(self, room_repo: RoomRepository, word_repo: WordRepository, group_repo: GroupRepository):
        self.room_repo = room_repo
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, owner_id: int, room_id: int, placements: list[PlacementInput]) -> PlaceWordsResult:
        room = _require_room_owner(self.room_repo, room_id, owner_id)
        placeable = {word.id: word for word in self.word_repo.list_by_group(room.group_id) if word.id is not None}

        applied: list[int] = []
        skipped: list[SkippedPlacement] = []
        for item in placements:
            word = placeable.get(item.word_id)
            if word is None:
                skipped.append(SkippedPlacement(item.word_id, self._miss_reason(item.word_id, owner_id)))
                continue
            try:
                room.place_word(word, item.x_percent, item.y_percent)
            except InvalidPlacementError:
                # `placeable` already guarantees the group invariant, so the
                # only way to land here is out-of-range coordinates.
                skipped.append(SkippedPlacement(item.word_id, "invalid_coordinates"))
                continue
            applied.append(item.word_id)

        # Skip the write entirely when nothing applied; an all-invalid batch
        # should not rewrite the aggregate to its own current value.
        if applied:
            room = self.room_repo.update(room)
        return PlaceWordsResult(room=room, applied=tuple(applied), skipped=tuple(skipped))

    def _miss_reason(self, word_id: int, owner_id: int) -> str:
        """Explain a miss without becoming a cross-account existence oracle.

        A word this account does not own is reported exactly as a word that
        does not exist. Distinguishing the two would let a caller holding one
        valid grant probe which word ids belong to other accounts, one batch
        item at a time. A word the caller *does* own but filed under another
        group is named precisely, because that is the ordinary mistake this
        reason exists to explain and it discloses nothing the caller cannot
        already read.

        Only misses pay these lookups, so a batch of valid placements still
        costs one room load, one group listing and one save.
        """
        word = self.word_repo.get_by_id(word_id)
        if word is not None:
            group = self.group_repo.get_by_id(word.group_id)
            if group is not None and group.owner_id == owner_id:
                return "word_in_different_group"
        return "word_not_found"


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
