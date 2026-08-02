"""Mistake decay and the "review my mistakes" selection (issue #142).

The claims worth pinning are the refusals: successes before the last mistake
do not count, time passing does not count, and a resolved mistake is left out
of the session rather than padding it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.services.mistake_memory import (
    SUCCESSES_TO_RESOLVE,
    MistakeMemory,
    RecordedMistake,
    build_memories,
    select_for_session,
    unresolved,
)

NOW = datetime(2026, 8, 2, 9, 0)


def _mistake(word_id: int = 1, days_ago: float = 1, category: str = "spelling", occurrences: int = 1):
    return RecordedMistake(
        word_id=word_id,
        occurred_at=NOW - timedelta(days=days_ago),
        category=category,
        occurrences=occurrences,
    )


# --- Decay -----------------------------------------------------------------


def test_an_unreviewed_mistake_is_at_full_strength():
    memory = build_memories([_mistake()], {})[0]

    assert memory.strength == 1.0
    assert memory.resolved is False


def test_each_correct_answer_decays_the_mistake():
    later = [NOW]
    memory = build_memories([_mistake(days_ago=2)], {1: later})[0]

    assert memory.strength < 1.0
    assert memory.successes_since == 1


def test_enough_correct_answers_resolve_it():
    successes = [NOW - timedelta(hours=h) for h in range(SUCCESSES_TO_RESOLVE)]
    memory = build_memories([_mistake(days_ago=5)], {1: successes})[0]

    assert memory.resolved is True
    assert memory.strength == 0.0


def test_strength_never_goes_below_zero():
    """A word answered correctly ten times is resolved, not negatively wrong."""
    successes = [NOW - timedelta(minutes=m) for m in range(10)]
    memory = build_memories([_mistake(days_ago=5)], {1: successes})[0]

    assert memory.strength == 0.0


def test_one_correct_answer_does_not_resolve_a_mistake():
    """Answering correctly immediately after being shown the answer is often
    repetition rather than recall."""
    memory = build_memories([_mistake(days_ago=1)], {1: [NOW]})[0]

    assert memory.resolved is False


# --- What does not count ---------------------------------------------------


def test_successes_before_the_mistake_do_not_count():
    """Getting a word right and then wrong again means the earlier success did
    not stick. Crediting it would retire a mistake the learner still has."""
    earlier = [NOW - timedelta(days=10), NOW - timedelta(days=9), NOW - timedelta(days=8)]
    memory = build_memories([_mistake(days_ago=1)], {1: earlier})[0]

    assert memory.successes_since == 0
    assert memory.strength == 1.0


def test_only_the_most_recent_mistake_sets_the_cutoff():
    mistakes = [_mistake(days_ago=10), _mistake(days_ago=1)]
    successes = [NOW - timedelta(days=5)]

    memory = build_memories(mistakes, {1: successes})[0]

    assert memory.successes_since == 0


def test_time_passing_does_not_resolve_anything():
    """A word untouched for a year has not been relearned, it has been
    avoided — which is why the input is a review log and not a duration."""
    memory = build_memories([_mistake(days_ago=365)], {})[0]

    assert memory.resolved is False
    assert memory.strength == 1.0


def test_correct_answers_for_other_words_are_ignored():
    memory = build_memories([_mistake(word_id=1)], {2: [NOW, NOW, NOW]})[0]

    assert memory.successes_since == 0


# --- Aggregation per word --------------------------------------------------


def test_repeated_mistakes_on_one_word_become_one_memory():
    memories = build_memories([_mistake(days_ago=3), _mistake(days_ago=1)], {})

    assert len(memories) == 1
    assert memories[0].mistake_count == 2


def test_occurrence_counts_are_summed_rather_than_counted_as_rows():
    memories = build_memories([_mistake(occurrences=4)], {})

    assert memories[0].mistake_count == 4


def test_every_category_that_produced_a_mistake_is_kept():
    """"You get this wrong on spelling and on sense" is more useful than a
    single label that discards one of them."""
    memories = build_memories(
        [_mistake(category="spelling"), _mistake(category="sense")], {}
    )

    assert memories[0].categories == ("sense", "spelling")


def test_the_last_mistake_time_is_the_most_recent_one():
    memories = build_memories([_mistake(days_ago=9), _mistake(days_ago=2)], {})

    assert memories[0].last_mistake_at == NOW - timedelta(days=2)


# --- Ordering --------------------------------------------------------------


def test_the_worst_mistakes_come_first():
    memories = build_memories(
        [_mistake(word_id=1, days_ago=1), _mistake(word_id=2, days_ago=1)],
        {1: [NOW]},  # word 1 partially recovered
    )

    assert memories[0].word_id == 2


def test_repetition_breaks_ties_before_recency():
    """A word missed five times last week is a bigger problem than one missed
    once yesterday. Ordering by recency alone keeps showing whatever was
    reviewed last."""
    memories = build_memories(
        [_mistake(word_id=1, days_ago=7, occurrences=5), _mistake(word_id=2, days_ago=1)], {}
    )

    assert [m.word_id for m in memories] == [1, 2]


# --- Session selection -----------------------------------------------------


def test_a_session_offers_the_worst_words_first():
    memories = build_memories(
        [_mistake(word_id=1, occurrences=1), _mistake(word_id=2, occurrences=9)], {}
    )

    assert select_for_session(memories, limit=2) == [2, 1]


def test_a_resolved_mistake_is_left_out_rather_than_ranked_last():
    """A session that pads itself with words the learner has already fixed
    misrepresents what it is."""
    successes = [NOW - timedelta(hours=h) for h in range(SUCCESSES_TO_RESOLVE)]
    memories = build_memories(
        [_mistake(word_id=1, days_ago=5), _mistake(word_id=2, days_ago=5)], {1: successes}
    )

    assert select_for_session(memories, limit=10) == [2]


def test_a_session_is_short_rather_than_padded_when_little_is_outstanding():
    memories = build_memories([_mistake(word_id=1)], {})

    assert select_for_session(memories, limit=20) == [1]


def test_the_limit_is_respected():
    memories = build_memories([_mistake(word_id=i) for i in range(1, 11)], {})

    assert len(select_for_session(memories, limit=3)) == 3


def test_a_zero_limit_selects_nothing():
    memories = build_memories([_mistake()], {})

    assert select_for_session(memories, limit=0) == []


def test_a_learner_with_no_mistakes_gets_an_empty_session():
    assert select_for_session([], limit=10) == []
    assert build_memories([], {}) == []


def test_unresolved_filters_out_what_is_done():
    memories = [
        MistakeMemory(1, 1, 0, 1.0, NOW, ("spelling",)),
        MistakeMemory(2, 1, SUCCESSES_TO_RESOLVE, 0.0, NOW, ("spelling",)),
    ]

    assert [m.word_id for m in unresolved(memories)] == [1]
