"""Reconciling offline mutations against the server's current state (issue #90).

`SyncMergePolicy` (domain) decides whether an operation may apply; this is
the caller that actually applies it, against the one entity type its rules
were written for end-to-end — words — plus review appends, which never
conflict by construction. File imports and local-AI results need no server
piece here: those endpoints already exist and are called once a client is
back online, so what is missing is a client-side queue, not a server-side
merge rule — out of scope for this use case, tracked separately.

Every operation gets an outcome, recorded before this returns: applied,
duplicate (idempotent replay), or conflict — including an ownership
violation, which is a conflict for the *operation* rather than a fault that
aborts the rest of the batch. A batch of ninety-nine good operations and one
bad one must not lose the ninety-nine.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.vocabulary import _require_group_owner
from app.domain.entities import Word
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.repositories import GroupRepository, WordRepository
from app.domain.services.sync_merge import SyncMergePolicy, SyncOperation, SyncStatus
from app.domain.value_objects import ReviewOutcome, SupportedLanguage

_WORD_FIELDS = (
    "term",
    "target_language",
    "translations",
    "example_sentence",
    "mnemonic",
    "category",
    "definition",
    "part_of_speech",
    "cefr_level",
    "pronunciation",
    "collocations",
    "tags",
    "synonyms",
    "antonyms",
    "topics",
)
_WORD_LIST_FIELDS = ("translations", "collocations", "tags", "synonyms", "antonyms", "topics")
_WORD_SCALAR_FIELDS = ("example_sentence", "mnemonic", "category", "definition", "part_of_speech", "cefr_level", "pronunciation")


@dataclass(frozen=True)
class SyncOperationInput:
    operation_id: str
    entity_type: str
    entity_id: int | None
    operation: str
    payload: dict
    base_revision: int | None


@dataclass(frozen=True)
class SyncOperationOutcome:
    operation_id: str
    status: str
    conflict_reason: str | None
    entity_id: int | None


def _word_to_dict(word: Word) -> dict:
    data = {f: getattr(word, f) for f in _WORD_FIELDS}
    data["target_language"] = word.target_language.value
    return data


def _apply_word_fields(word: Word, data: dict) -> None:
    """Partial patch: a key absent from `data` leaves that field untouched —
    an offline edit only names what it actually changed."""
    if isinstance(data.get("term"), str) and data["term"].strip():
        word.term = data["term"].strip()
    if "target_language" in data:
        word.target_language = SupportedLanguage(data["target_language"])
    for key in _WORD_SCALAR_FIELDS:
        if key in data:
            setattr(word, key, data[key])
    for key in _WORD_LIST_FIELDS:
        if key in data and isinstance(data[key], list):
            setattr(word, key, [v.strip() for v in data[key] if isinstance(v, str) and v.strip()])


class SubmitSyncOperationsUseCase:
    def __init__(
        self,
        sync_repo,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        review_use_case=None,
    ):
        self.sync_repo = sync_repo
        self.word_repo = word_repo
        self.group_repo = group_repo
        # Optional so a caller that only exercises word sync need not wire a
        # full review-session stack. Reviews route through the existing
        # SubmitAnswerUseCase rather than writing attempts directly, so
        # scheduling, mistake recording and session bookkeeping stay in the
        # one place that already owns them.
        self.review_use_case = review_use_case

    def execute(self, user_id: int, operations: list[SyncOperationInput]) -> list[SyncOperationOutcome]:
        return [self._apply_one(user_id, op) for op in operations]

    def _apply_one(self, user_id: int, op: SyncOperationInput) -> SyncOperationOutcome:
        existing = self.sync_repo.find(user_id, op.operation_id)
        if existing is not None:
            # A retry after a lost response. Not re-applied — the whole point
            # of naming a stable operation id is that this returns the same
            # outcome the first submission got, not a second attempt at it.
            return SyncOperationOutcome(
                op.operation_id, existing.status, existing.conflict_reason, existing.entity_id
            )

        try:
            if op.entity_type == "word":
                status, reason, entity_id = self._apply_word(user_id, op)
            elif op.entity_type == "review":
                status, reason, entity_id = self._apply_review(user_id, op)
            else:
                status, reason, entity_id = SyncStatus.CONFLICT.value, f"unknown entity_type '{op.entity_type}'", op.entity_id
        except (EntityNotFoundError, PermissionDeniedError, ValueError) as exc:
            # An ownership violation or a malformed operation kind is a
            # conflict for *this* operation, not a fault that aborts
            # everything after it in the batch.
            status, reason, entity_id = SyncStatus.CONFLICT.value, str(exc), op.entity_id

        self.sync_repo.record(
            user_id=user_id,
            operation_id=op.operation_id,
            entity_type=op.entity_type,
            entity_id=entity_id,
            operation=op.operation,
            payload=op.payload,
            base_revision=op.base_revision,
            status=status,
            conflict_reason=reason,
        )
        return SyncOperationOutcome(op.operation_id, status, reason, entity_id)

    def _word_ownership(self, entity_id: int | None, user_id: int) -> tuple[Word | None, bool]:
        """`(word, exists)`. Raises PermissionDeniedError if the word exists
        but belongs to someone else — that is a security boundary, never a
        reconcilable conflict. `exists=False` covers both "never created"
        and "deleted elsewhere", which the merge policy treats the same."""
        if entity_id is None:
            return None, False
        word = self.word_repo.get_by_id(entity_id)
        if word is None:
            return None, False
        _require_group_owner(self.group_repo, word.group_id, user_id)
        return word, True

    def _apply_word(self, user_id: int, op: SyncOperationInput) -> tuple[str, str | None, int | None]:
        kind = SyncOperation(op.operation)

        if kind is SyncOperation.CREATE:
            group_id = op.payload.get("group_id")
            _require_group_owner(self.group_repo, group_id, user_id)
            word = Word(id=None, group_id=group_id, term="", target_language=SupportedLanguage.ENGLISH)
            _apply_word_fields(word, op.payload)
            created = self.word_repo.add(word)
            return SyncStatus.APPLIED.value, None, created.id

        current, exists = self._word_ownership(op.entity_id, user_id)
        decision = SyncMergePolicy.decide(
            kind, op.base_revision, current.revision if current else None, exists
        )
        if not decision.applies:
            return SyncStatus.CONFLICT.value, decision.reason, op.entity_id

        if kind is SyncOperation.DELETE:
            if exists:
                self.word_repo.delete(op.entity_id)
            return SyncStatus.APPLIED.value, None, op.entity_id

        # UPDATE and APPEND both reach here; a word has no append-shaped
        # field today, so APPEND behaves like UPDATE — merge whatever the
        # payload names.
        merged = SyncMergePolicy.merge_collections(_word_to_dict(current), op.payload)
        _apply_word_fields(current, merged)
        self.word_repo.update(current)
        return SyncStatus.APPLIED.value, None, op.entity_id

    def _apply_review(self, user_id: int, op: SyncOperationInput) -> tuple[str, str | None, int | None]:
        if op.operation != SyncOperation.APPEND.value:
            raise ValueError("a review may only be appended, never created/updated/deleted")
        if self.review_use_case is None:
            raise ValueError("review sync is not configured on this server")

        self.review_use_case.execute(
            user_id=user_id,
            session_id=op.payload.get("session_id"),
            word_id=op.payload.get("word_id"),
            outcome=ReviewOutcome(op.payload.get("outcome")),
            response_time_ms=op.payload.get("response_time_ms"),
            attempted_answer=op.payload.get("attempted_answer"),
        )
        # Appends are commutative and never conflict (SyncMergePolicy), so
        # there is nothing to decide here — only whether it could be applied
        # at all, which the exception paths above already cover.
        return SyncStatus.APPLIED.value, None, op.payload.get("word_id")
