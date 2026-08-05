"""AI provenance and verification rules (issue #140).

The rule worth testing hardest is the one that costs something: a model
rewriting a field ends its verification. It is tempting to keep the badge —
the word is still "checked" in some loose sense — and that is exactly how a
verified badge comes to vouch for text nobody read.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.services.ai_provenance import (
    AI_AUTHORED_FIELDS,
    EditSource,
    FieldChange,
    changed_fields,
    is_ai_generated,
    verification_state,
    verification_survives,
)

NOW = datetime(2026, 8, 2, 9, 0)


# --- What counts as a change -----------------------------------------------


def test_a_differing_field_is_reported():
    assert changed_fields({"definition": "a cat"}, {"definition": "a small cat"}) == ["definition"]


def test_an_unchanged_field_is_not_reported():
    assert changed_fields({"definition": "a cat"}, {"definition": "a cat"}) == []


def test_reordering_a_list_counts_as_a_change():
    """The learner did that on purpose."""
    before = {"synonyms": ["gato", "minino"]}
    after = {"synonyms": ["minino", "gato"]}

    assert changed_fields(before, after) == ["synonyms"]


def test_rewriting_the_same_list_is_not_a_change():
    """Otherwise every save fills the history with entries describing nothing."""
    assert changed_fields({"synonyms": ["gato"]}, {"synonyms": ["gato"]}) == []


def test_whitespace_only_differences_are_not_changes():
    assert changed_fields({"definition": "a cat"}, {"definition": "  a cat  "}) == []


def test_empty_and_absent_are_the_same_absence():
    """A history entry recording None becoming "" describes nothing."""
    assert changed_fields({"mnemonic": None}, {"mnemonic": "   "}) == []


def test_untracked_fields_are_ignored():
    """A field not in the closed list is never treated as AI-authored, so
    adding one is a decision rather than a side effect of adding a column."""
    assert changed_fields({"term": "gato"}, {"term": "perro"}) == []


def test_the_tracked_field_list_is_closed_and_non_empty():
    assert "definition" in AI_AUTHORED_FIELDS
    assert "term" not in AI_AUTHORED_FIELDS


# --- Verification survival -------------------------------------------------


def test_a_model_rewriting_a_verified_field_ends_verification():
    """The badge says a person read this text. After re-enrichment that is no
    longer true of what is on screen."""
    assert verification_survives(["definition"], EditSource.AI) is False


def test_a_human_editing_what_they_verified_keeps_it_verified():
    """They are the one who checked it; their own correction does not make it
    unchecked."""
    assert verification_survives(["definition"], EditSource.HUMAN) is True


def test_a_bulk_edit_keeps_verification():
    assert verification_survives(["cefr_level"], EditSource.BULK) is True


def test_a_change_that_changed_nothing_never_ends_verification():
    """Re-saving an untouched card must not quietly strip the badge."""
    assert verification_survives([], EditSource.AI) is True


# --- Describing a card -----------------------------------------------------


def test_a_card_no_model_touched_is_human():
    assert verification_state(None, None) == "human"


def test_a_model_written_card_starts_unverified():
    assert verification_state("ollama", None) == "unverified"


def test_a_checked_model_card_is_verified():
    assert verification_state("ollama", NOW) == "verified"


def test_verified_and_human_stay_distinguishable():
    """Collapsing them would hide which cards were ever machine-written."""
    assert verification_state("ollama", NOW) != verification_state(None, None)


def test_a_human_card_is_never_called_unverified():
    """There is nothing to verify — nobody claimed a model wrote it."""
    assert verification_state(None, NOW) == "human"


@pytest.mark.parametrize("provider,expected", [("ollama", True), ("", False), (None, False)])
def test_ai_generated_is_decided_by_provider(provider, expected):
    assert is_ai_generated(provider) is expected


# --- The change record -----------------------------------------------------


def test_a_change_knows_whether_a_model_made_it():
    ai = FieldChange("definition", "a", "b", EditSource.AI, NOW)
    human = FieldChange("definition", "a", "b", EditSource.HUMAN, NOW)

    assert ai.is_ai_authored is True
    assert human.is_ai_authored is False


def test_a_bulk_edit_is_not_recorded_as_an_ordinary_human_edit():
    """"I changed this card" and "I set the level on forty cards" are different
    degrees of attention, and conflating them overstates the second."""
    assert EditSource.BULK != EditSource.HUMAN
    assert FieldChange("cefr_level", "A1", "B1", EditSource.BULK, NOW).is_ai_authored is False
