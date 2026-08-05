"""Who wrote what on a word, and whether a human has checked it (issue #140).

Words already carry `ai_provider`, `ai_model` and `ai_confidence`, so we know a
card came from a model. What was missing is the other half: whether anyone
looked at it afterwards, and what it said before.

**Verification is a claim about specific text, not about a word.** "A human
checked this" is only true of the text they saw. If the model later rewrites a
field, the badge would be vouching for words nobody read — so re-enrichment
clears verification. That is the whole reason `verification_survives` exists
rather than a bare boolean on the row.

**A human edit is not an AI field any more.** Editing a model-written
definition makes it the learner's definition. It does not need verifying, and
it must not keep claiming to be AI-generated, because provenance that survives
being overwritten is a lie about where the text came from.

Pure: it decides, it does not persist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# Fields a model can write and a human can therefore be asked to verify.
# Deliberately closed: a field not listed here is never treated as AI-authored,
# so adding one is a decision rather than a side effect of adding a column.
AI_AUTHORED_FIELDS = (
    "translations",
    "definition",
    "example_sentence",
    "mnemonic",
    "part_of_speech",
    "cefr_level",
    "pronunciation",
    "collocations",
    "synonyms",
    "antonyms",
    "topics",
)


class EditSource(str, Enum):
    """Who made a change. Recorded, never inferred after the fact."""

    AI = "ai"
    HUMAN = "human"
    # A bulk edit applied to many candidates at once (#140). Distinguished from
    # a single human edit because "I changed this one card" and "I set the
    # level on forty cards" are different degrees of attention, and a history
    # that conflated them would overstate how carefully the bulk one was made.
    BULK = "bulk"


@dataclass(frozen=True)
class FieldChange:
    """One field moving from one value to another."""

    field: str
    before: str | None
    after: str | None
    source: EditSource
    changed_at: datetime

    @property
    def is_ai_authored(self) -> bool:
        return self.source is EditSource.AI


def changed_fields(before: dict, after: dict, fields=AI_AUTHORED_FIELDS) -> list[str]:
    """Which of the tracked fields actually differ.

    Compared by value rather than by identity, and lists are compared as lists:
    reordering synonyms is a change the learner made and should be recorded,
    while rewriting the same list in the same order is not a change at all and
    must not fill the history with noise.
    """
    return [name for name in fields if _normalise(before.get(name)) != _normalise(after.get(name))]


def verification_survives(changes: list[str], source: EditSource) -> bool:
    """Whether a verified word stays verified after this change.

    A human editing what they verified keeps the verification: they are the
    one who checked it, and their own correction does not make it unchecked.

    A model rewriting a verified field ends it. The badge says a person read
    this text, and after re-enrichment that is no longer true of the text on
    screen — leaving it set would make the badge worthless exactly when it
    matters.
    """
    if not changes:
        return True
    return source is not EditSource.AI


def is_ai_generated(provider: str | None) -> bool:
    return bool(provider)


def verification_state(
    provider: str | None, verified_at: datetime | None
) -> str:
    """How the card should be described, in one word.

    Three states rather than two, because "written by a model and checked" and
    "written by a person" are different facts and collapsing them would hide
    which cards were ever machine-written.
    """
    if not is_ai_generated(provider):
        return "human"
    return "verified" if verified_at is not None else "unverified"


def _normalise(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        # Empty and absent are the same absence. Recording a change from None
        # to "" would be a history entry describing nothing.
        return stripped or None
    return value
