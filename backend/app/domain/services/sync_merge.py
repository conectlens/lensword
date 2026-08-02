"""Merge rules for offline mutations (issue #90).

The rules differ by *shape of edit*, not by entity, which is the thing worth
getting right:

- **Appends never conflict.** A review is a fact about a moment — "I answered
  this word correctly at 09:14" — and two devices appending two reviews are
  both telling the truth. Version-checking them would reject real data to
  protect an ordering nobody asked for.

- **Scalar edits use a version check.** Two devices setting a word's
  translation to different strings cannot both win, and picking one by arrival
  time picks by network conditions.

- **Collections merge by stable item id.** Adding a synonym on one device and a
  different synonym on another is not a conflict; both belong. Merging by
  position would lose one, and comparing whole lists would call it a conflict.

Nothing here writes. It decides, and the caller applies — so the rules can be
tested against the cases the issue names (retry, reordering, duplicates,
concurrent edits, delete-vs-edit) without a database.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SyncOperation(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    # An append is distinguished from an update at the protocol level rather
    # than inferred from the entity, so a client says what it means and the
    # server does not have to guess which rule applies.
    APPEND = "append"


class SyncStatus(str, Enum):
    APPLIED = "applied"
    # Recorded, kept, and surfaced. Never discarded: the issue is explicit that
    # neither version may be silently dropped.
    CONFLICT = "conflict"
    # Already seen. The operation was applied by an earlier submission of the
    # same operation id, and this one is a retry.
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class MergeDecision:
    status: SyncStatus
    reason: str | None = None

    @property
    def applies(self) -> bool:
        return self.status is SyncStatus.APPLIED


# Fields that merge as sets rather than being overwritten. Adding "formal" to a
# word's tags on a laptop and "verb" on a phone should end with both.
COLLECTION_FIELDS = frozenset({"translations", "synonyms", "antonyms", "topics", "collocations"})


class SyncMergePolicy:
    """Stateless. Decides whether one operation may be applied."""

    @staticmethod
    def decide(
        operation: SyncOperation,
        base_revision: int | None,
        current_revision: int | None,
        entity_exists: bool,
    ) -> MergeDecision:
        """Whether to apply, and if not, why.

        `current_revision` is None when the entity is gone — deleted on another
        device, or never created. That is deliberately distinguished from
        "revision zero" so delete-vs-edit is decidable rather than guessed at.
        """
        if operation is SyncOperation.CREATE:
            # A create needs no base: nothing existed to be stale against.
            return MergeDecision(SyncStatus.APPLIED)

        if not entity_exists:
            if operation is SyncOperation.DELETE:
                # Deleting something already gone is the outcome the caller
                # wanted. Converging, not conflicting.
                return MergeDecision(SyncStatus.APPLIED)
            # Edit-vs-delete. Surfaced rather than resolved: re-creating the
            # entity would resurrect something deliberately removed, and
            # dropping the edit would lose work done offline. A person decides.
            return MergeDecision(
                SyncStatus.CONFLICT,
                "edited on this device but deleted on another",
            )

        if operation is SyncOperation.APPEND:
            # Appends are commutative, so ordering and staleness are both
            # irrelevant. This is why a week of offline reviews from two
            # devices reconciles without a single conflict.
            return MergeDecision(SyncStatus.APPLIED)

        if base_revision is None:
            # An update that names no base cannot be checked, so it would be
            # last-write-wins by another name. Refused rather than silently
            # accepted.
            return MergeDecision(SyncStatus.CONFLICT, "update did not state the revision it edited")

        if base_revision == current_revision:
            return MergeDecision(SyncStatus.APPLIED)

        return MergeDecision(
            SyncStatus.CONFLICT,
            f"edited revision {base_revision}, which is now revision {current_revision}",
        )

    @staticmethod
    def merge_collections(current: dict, incoming: dict) -> dict:
        """Union the collection fields, take the rest from `incoming`.

        Order is preserved and duplicates removed, with current entries first:
        a client that reconciles repeatedly should see a stable list rather
        than one that reshuffles on every sync.
        """
        merged = dict(incoming)
        for field in COLLECTION_FIELDS & incoming.keys():
            existing = current.get(field) or []
            added = [item for item in (incoming.get(field) or []) if item not in existing]
            merged[field] = list(existing) + added
        return merged
