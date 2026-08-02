"""What the conversation tutor is told, and what it may say back (issue #135).

The injected material is the learner's own vocabulary and mistakes — exactly
the content a user can author, and therefore exactly what must never be read as
an instruction. Most of these tests are about bounds and refusals.
"""
from __future__ import annotations

import pytest

from app.domain.services.conversation import (
    MAX_CORRECTIONS_PER_TURN,
    MAX_HISTORY_TURNS,
    MAX_MISTAKE_HINTS,
    MAX_VOCABULARY_HINTS,
    Difficulty,
    Speaker,
    Turn,
    build_context,
    validate_reply,
)


def _history(count: int) -> list[Turn]:
    return [
        Turn(speaker=Speaker.LEARNER if i % 2 == 0 else Speaker.TUTOR, text=f"turn {i}")
        for i in range(count)
    ]


def _context(**over):
    defaults = dict(
        target_language="Spanish",
        difficulty=Difficulty.STEADY,
        vocabulary=[],
        recent_mistakes=[],
        history=[],
    )
    return build_context(**{**defaults, **over})


# --- Bounding the prompt ----------------------------------------------------


def test_history_is_trimmed_to_the_most_recent_turns():
    """A conversation that grows without limit eventually pushes the system
    instruction out of the context window, and the tutor stops behaving like a
    tutor partway through a long chat."""
    context = _context(history=_history(50))

    assert len(context.history) == MAX_HISTORY_TURNS


def test_trimming_keeps_the_recent_end_not_the_start():
    """Dropping recent turns would make the tutor forget what was just said
    while remembering the opening, which reads as not listening."""
    context = _context(history=_history(50))

    assert context.history[-1].text == "turn 49"


def test_vocabulary_hints_are_bounded():
    context = _context(vocabulary=[f"word{i}" for i in range(200)])

    assert len(context.vocabulary) == MAX_VOCABULARY_HINTS


def test_mistake_hints_are_kept_small():
    """The tutor should weave in a few known weak points, not run a remedial
    drill."""
    context = _context(recent_mistakes=[f"m{i}" for i in range(50)])

    assert len(context.recent_mistakes) == MAX_MISTAKE_HINTS


def test_a_long_message_is_clipped():
    context = _context(history=[Turn(speaker=Speaker.LEARNER, text="x" * 9000)])

    assert len(context.history[0].text) <= 2000


def test_empty_turns_are_dropped_rather_than_sent_as_blanks():
    context = _context(
        history=[Turn(speaker=Speaker.LEARNER, text="  "), Turn(speaker=Speaker.TUTOR, text="hola")]
    )

    assert [t.text for t in context.history] == ["hola"]


# --- Cleaning the injected lists --------------------------------------------


def test_duplicate_vocabulary_is_collapsed():
    context = _context(vocabulary=["gato", "Gato", " gato "])

    assert context.vocabulary == ["gato"]


def test_the_callers_ordering_is_preserved():
    """Callers pass most-relevant-first, and sorting here would silently
    discard that ranking when the list is trimmed."""
    context = _context(vocabulary=["zebra", "alpha", "mango"])

    assert context.vocabulary == ["zebra", "alpha", "mango"]


def test_non_string_entries_are_ignored():
    context = _context(vocabulary=["gato", None, 42, "perro"])

    assert context.vocabulary == ["gato", "perro"]


# --- Validating what comes back ---------------------------------------------


def _reply(**over):
    return {"reply": "¡Claro!", **over}


def test_a_plain_reply_is_accepted():
    reply, corrections = validate_reply(_reply(), "hola")

    assert reply == "¡Claro!"
    assert corrections == []


def test_an_empty_reply_is_refused():
    with pytest.raises(ValueError):
        validate_reply({"reply": "   "}, "hola")


def test_a_non_dict_response_is_refused():
    with pytest.raises(ValueError):
        validate_reply(["nope"], "hola")


def test_a_correction_quoting_the_learner_is_kept():
    raw = _reply(
        corrections=[
            {"original": "yo tiene", "corrected": "yo tengo", "explanation": "first person"}
        ]
    )

    _, corrections = validate_reply(raw, "yo tiene un gato")

    assert corrections[0].corrected == "yo tengo"


def test_a_correction_quoting_text_the_learner_never_wrote_is_dropped():
    """A highlight pointing at words nobody typed teaches the learner to ignore
    highlights entirely, and then the useful ones get ignored too."""
    raw = _reply(
        corrections=[{"original": "el perro grande", "corrected": "el perro pequeño", "explanation": ""}]
    )

    _, corrections = validate_reply(raw, "yo tengo un gato")

    assert corrections == []


def test_correction_matching_ignores_case():
    raw = _reply(corrections=[{"original": "Yo Tiene", "corrected": "yo tengo", "explanation": ""}])

    _, corrections = validate_reply(raw, "yo tiene un gato")

    assert len(corrections) == 1


def test_a_correction_that_changes_nothing_is_dropped():
    raw = _reply(corrections=[{"original": "gato", "corrected": "gato", "explanation": ""}])

    _, corrections = validate_reply(raw, "un gato")

    assert corrections == []


def test_corrections_are_capped_per_turn():
    """Correcting everything turns a conversation into a test, and learners
    stop talking."""
    said = "a b c d e f"
    raw = _reply(
        corrections=[
            {"original": letter, "corrected": letter.upper() + "!", "explanation": ""}
            for letter in "abcdef"
        ]
    )

    _, corrections = validate_reply(raw, said)

    assert len(corrections) == MAX_CORRECTIONS_PER_TURN


def test_malformed_corrections_are_skipped_rather_than_failing_the_turn():
    """One bad entry must not cost the learner their reply."""
    raw = _reply(
        corrections=[
            "not a dict",
            {"original": "", "corrected": "x"},
            {"original": "gato", "corrected": "gata", "explanation": "gender"},
        ]
    )

    reply, corrections = validate_reply(raw, "un gato")

    assert reply == "¡Claro!"
    assert len(corrections) == 1


def test_a_missing_corrections_key_is_not_an_error():
    _, corrections = validate_reply({"reply": "hola"}, "hola")

    assert corrections == []


def test_an_explanation_is_optional():
    raw = _reply(corrections=[{"original": "gato", "corrected": "gata"}])

    _, corrections = validate_reply(raw, "un gato")

    assert corrections[0].explanation == ""


# --- Difficulty -------------------------------------------------------------


def test_difficulty_is_named_rather_than_numeric():
    """"B1-ish" is something a learner can choose meaningfully; "difficulty
    0.7" is a number they would be guessing at."""
    assert {d.value for d in Difficulty} == {"gentle", "steady", "stretch"}


def test_the_context_carries_the_chosen_difficulty():
    assert _context(difficulty=Difficulty.STRETCH).difficulty is Difficulty.STRETCH
