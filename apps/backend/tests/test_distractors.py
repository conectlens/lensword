"""Semantically related multiple-choice distractors (issue #205)."""
from __future__ import annotations

import random

import pytest

from app.domain.entities import Word
from app.domain.services.distractors import (
    DEFAULT_MIN_ACCOUNT_STRENGTH_FOR_COMPETITIVE_DISTRACTORS,
    DEFAULT_MIN_STABILITY_FOR_COMPETITIVE_DISTRACTORS,
    MAX_DISTRACTORS,
    select_distractors,
)
from app.domain.services.knowledge_graph import KnowledgeGraph, WordNode, build_edges
from app.domain.value_objects import ReviewState


def _word(word_id: int, term: str, translation: str) -> Word:
    return Word(id=word_id, group_id=1, term=term, target_language="Spanish", translations=[translation])


def _state(stability: float | None) -> ReviewState:
    state = ReviewState.initial()
    return ReviewState(
        strength=state.strength, ease_factor=state.ease_factor, interval_days=state.interval_days,
        repetitions=1, due_at=state.due_at, last_reviewed_at=None, stability=stability,
    )


ESTABLISHED = DEFAULT_MIN_STABILITY_FOR_COMPETITIVE_DISTRACTORS + 1
PROFICIENT = DEFAULT_MIN_ACCOUNT_STRENGTH_FOR_COMPETITIVE_DISTRACTORS + 1
BELOW = DEFAULT_MIN_ACCOUNT_STRENGTH_FOR_COMPETITIVE_DISTRACTORS - 1


def _graph(*, borrow_synonym=True, borrow_confused=False) -> tuple[KnowledgeGraph, Word, Word, Word, Word]:
    borrow = _word(1, "borrow", "pedir prestado")
    lend = _word(2, "lend", "prestar")
    table = _word(3, "table", "mesa")
    chair = _word(4, "chair", "silla")

    nodes = [
        WordNode(word_id=1, term="borrow", synonyms=("lend",) if borrow_synonym else ()),
        WordNode(word_id=2, term="lend"),
        WordNode(word_id=3, term="table"),
        WordNode(word_id=4, term="chair"),
    ]
    confusions = {(1, 3): 5} if borrow_confused else None
    graph = KnowledgeGraph(nodes, build_edges(nodes, confusions=confusions))
    return graph, borrow, lend, table, chair


def test_an_established_word_in_a_proficient_account_gets_a_competitive_distractor():
    graph, borrow, lend, table, chair = _graph()

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
        graph=graph, review_state=_state(ESTABLISHED), account_average_strength=PROFICIENT,
        count=1, rng=random.Random(0),
    )

    assert selection.competitive == {"prestar"}
    assert "prestar" in selection.options
    assert "pedir prestado" in selection.options


def test_a_new_word_falls_back_to_a_random_distractor():
    graph, borrow, lend, table, chair = _graph()

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
        graph=graph, review_state=_state(None), account_average_strength=PROFICIENT,
        count=1, rng=random.Random(0),
    )

    assert selection.competitive == frozenset()


def test_a_word_below_the_stability_threshold_falls_back_to_a_random_distractor():
    graph, borrow, lend, table, chair = _graph()

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
        graph=graph, review_state=_state(ESTABLISHED - 100), account_average_strength=PROFICIENT,
        count=1, rng=random.Random(0),
    )

    assert selection.competitive == frozenset()


def test_a_weak_account_never_gets_competitive_distractors_even_for_an_established_word():
    """TODO 4: Baxter et al. found the benefit limited to skilled readers —
    weaker accounts pay the accuracy cost with no later benefit."""
    graph, borrow, lend, table, chair = _graph()

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
        graph=graph, review_state=_state(ESTABLISHED), account_average_strength=BELOW,
        count=1, rng=random.Random(0),
    )

    assert selection.competitive == frozenset()


def test_confused_with_neighbours_are_never_offered_as_distractors():
    """A word already confused with the target is the learner's own most
    confusable word for it — offering it back defeats the exercise rather
    than exercising discrimination against a merely *related* word."""
    graph, borrow, lend, table, chair = _graph(borrow_synonym=False, borrow_confused=True)

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
        graph=graph, review_state=_state(ESTABLISHED), account_average_strength=PROFICIENT,
        count=1, rng=random.Random(0),
    )

    assert selection.competitive == frozenset()
    assert "mesa" not in selection.options  # table, the CONFUSED_WITH neighbour


def test_too_few_graph_neighbours_falls_back_to_filling_the_rest_from_the_pool():
    """The actual fix for the 'None of the above' defect (TODO 5): the pool
    is the caller's whole vocabulary, not a small already-loaded queue."""
    graph, borrow, lend, table, chair = _graph()

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
        graph=graph, review_state=_state(ESTABLISHED), account_average_strength=PROFICIENT,
        count=3, rng=random.Random(0),
    )

    assert len(selection.options) == 4  # correct + 3 distractors, no filler needed
    assert "None of the above" not in selection.options
    assert selection.competitive == {"prestar"}


def test_distractor_count_is_capped_regardless_of_what_is_requested():
    graph, borrow, lend, table, chair = _graph()
    fifth = _word(5, "window", "ventana")

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado",
        candidate_words=[borrow, lend, table, chair, fifth],
        graph=graph, review_state=_state(ESTABLISHED), account_average_strength=PROFICIENT,
        count=MAX_DISTRACTORS + 5, rng=random.Random(0),
    )

    assert len(selection.options) == MAX_DISTRACTORS + 1  # + the correct answer


def test_the_correct_answer_is_never_duplicated_as_a_distractor():
    graph, borrow, lend, table, chair = _graph()
    duplicate = _word(6, "borrow-again", "pedir prestado")

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado",
        candidate_words=[borrow, lend, table, chair, duplicate],
        graph=graph, review_state=_state(ESTABLISHED), account_average_strength=PROFICIENT,
        count=3, rng=random.Random(0),
    )

    assert selection.options.count("pedir prestado") == 1


def test_a_pool_too_small_to_fill_every_slot_degrades_gracefully():
    graph, borrow, lend, _table, _chair = _graph()

    selection = select_distractors(
        target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend],
        graph=graph, review_state=_state(None), account_average_strength=PROFICIENT,
        count=3, rng=random.Random(0),
    )

    assert selection.options == ["pedir prestado", "prestar"]


def test_selection_is_deterministic_given_the_same_rng_seed():
    graph, borrow, lend, table, chair = _graph()

    def run():
        return select_distractors(
            target=borrow, correct_answer="pedir prestado", candidate_words=[borrow, lend, table, chair],
            graph=graph, review_state=_state(ESTABLISHED), account_average_strength=PROFICIENT,
            count=2, rng=random.Random(42),
        )

    assert run().options == run().options
