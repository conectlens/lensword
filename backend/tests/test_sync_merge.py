"""Merge rules for offline mutations (issue #90).

The issue names the cases that have to be covered: retry, reordering,
duplicated requests, concurrent edits, delete-vs-edit, and multi-device review
events with zero lost acknowledged mutations. These cover the decision half —
what may be applied and what must be surfaced — without a database, which is
why the policy takes revisions rather than repositories.
"""
from __future__ import annotations

import pytest

from app.domain.services.sync_merge import (
    COLLECTION_FIELDS,
    MergeDecision,
    SyncMergePolicy,
    SyncOperation,
    SyncStatus,
)


def _decide(operation, base=None, current=1, exists=True) -> MergeDecision:
    return SyncMergePolicy.decide(operation, base, current, exists)


# --- Appends never conflict ------------------------------------------------


def test_an_append_applies_regardless_of_staleness():
    """A review is a fact about a moment. Two devices appending two reviews are
    both telling the truth, and version-checking them would reject real data to
    protect an ordering nobody asked for."""
    assert _decide(SyncOperation.APPEND, base=1, current=99).applies


def test_appends_from_two_devices_both_apply():
    """Multi-device review events with zero lost mutations, which the issue
    names explicitly."""
    phone = _decide(SyncOperation.APPEND, base=3, current=3)
    laptop = _decide(SyncOperation.APPEND, base=3, current=4)

    assert phone.applies and laptop.applies


def test_an_append_needs_no_base_revision():
    assert _decide(SyncOperation.APPEND, base=None, current=7).applies


# --- Scalar edits use a version check --------------------------------------


def test_an_edit_against_the_current_revision_applies():
    assert _decide(SyncOperation.UPDATE, base=4, current=4).applies


def test_an_edit_against_a_stale_revision_conflicts():
    """Two devices setting a translation to different strings cannot both win,
    and picking by arrival time picks by network conditions."""
    decision = _decide(SyncOperation.UPDATE, base=3, current=5)

    assert decision.status is SyncStatus.CONFLICT
    assert "revision 3" in decision.reason
    assert "revision 5" in decision.reason


def test_an_edit_that_states_no_revision_conflicts():
    """Otherwise it is last-write-wins wearing a different name."""
    decision = _decide(SyncOperation.UPDATE, base=None, current=5)

    assert decision.status is SyncStatus.CONFLICT
    assert "did not state the revision" in decision.reason


def test_reordering_does_not_change_the_outcome():
    """Two operations arriving in either order produce the same pair of
    decisions, because each is judged against the revision it names rather than
    against the one before it in the batch."""
    first = _decide(SyncOperation.UPDATE, base=4, current=4)
    second = _decide(SyncOperation.UPDATE, base=4, current=5)

    assert first.applies
    assert second.status is SyncStatus.CONFLICT


# --- Creates ---------------------------------------------------------------


def test_a_create_needs_no_base_revision():
    """Nothing existed for it to be stale against."""
    assert _decide(SyncOperation.CREATE, base=None, current=None, exists=False).applies


# --- Delete versus edit ----------------------------------------------------


def test_deleting_something_already_gone_converges():
    """The caller wanted it gone and it is gone. Conflicting here would make
    every retry of a delete a problem to resolve."""
    assert _decide(SyncOperation.DELETE, base=2, current=None, exists=False).applies


def test_editing_something_deleted_elsewhere_is_surfaced():
    """Neither answer is safe to pick: re-creating resurrects something
    deliberately removed, and dropping the edit loses work done offline."""
    decision = _decide(SyncOperation.UPDATE, base=2, current=None, exists=False)

    assert decision.status is SyncStatus.CONFLICT
    assert "deleted on another" in decision.reason


def test_appending_to_something_deleted_elsewhere_is_surfaced():
    """Appends are otherwise unconditional, but there is nothing to append to."""
    assert _decide(SyncOperation.APPEND, current=None, exists=False).status is SyncStatus.CONFLICT


# --- Collection merging ----------------------------------------------------


def test_collections_union_rather_than_overwrite():
    """Adding a synonym on a laptop and a different one on a phone is not a
    conflict; both belong."""
    merged = SyncMergePolicy.merge_collections(
        {"synonyms": ["fast"]}, {"synonyms": ["quick"], "term": "rapido"}
    )

    assert merged["synonyms"] == ["fast", "quick"]


def test_merging_preserves_order_and_drops_duplicates():
    """A client reconciling repeatedly should see a stable list rather than one
    that reshuffles on every sync."""
    merged = SyncMergePolicy.merge_collections(
        {"topics": ["a", "b"]}, {"topics": ["b", "c"]}
    )

    assert merged["topics"] == ["a", "b", "c"]


def test_scalar_fields_are_taken_from_the_incoming_edit():
    merged = SyncMergePolicy.merge_collections({"term": "old"}, {"term": "new"})

    assert merged["term"] == "new"


def test_a_collection_absent_from_the_edit_is_left_alone():
    """An edit that says nothing about synonyms must not clear them."""
    merged = SyncMergePolicy.merge_collections({"synonyms": ["fast"]}, {"term": "rapido"})

    assert "synonyms" not in merged


@pytest.mark.parametrize("field", sorted(COLLECTION_FIELDS))
def test_every_declared_collection_field_merges(field):
    merged = SyncMergePolicy.merge_collections({field: ["x"]}, {field: ["y"]})

    assert merged[field] == ["x", "y"]
