"""Semantic separation when introducing new words (issue #204)."""
from __future__ import annotations

from app.domain.services.knowledge_graph import WordNode
from app.domain.services.semantic_diversity import order_for_diversity


def _node(word_id: int, term: str, **kwargs) -> WordNode:
    return WordNode(word_id=word_id, term=term, **kwargs)


def test_an_unrelated_batch_is_left_in_its_original_order():
    candidates = [_node(0, "table"), _node(1, "run"), _node(2, "happy")]

    result = order_for_diversity(candidates)

    assert result.order == [0, 1, 2]
    assert result.deferred_for_recent_study == frozenset()


def test_a_semantic_set_is_spread_apart_not_introduced_consecutively():
    """Four colours (a classic semantic set) must not land as the first
    four items — the exact pattern the cited studies manipulated. Three
    unrelated fillers is exactly enough to separate all four (task-
    scheduler math: k items need k-1 gaps)."""
    candidates = [
        _node(0, "red", topics=("colours",)),
        _node(1, "blue", topics=("colours",)),
        _node(2, "green", topics=("colours",)),
        _node(3, "yellow", topics=("colours",)),
        _node(4, "table"),
        _node(5, "run"),
        _node(6, "happy"),
    ]

    result = order_for_diversity(candidates)

    colour_positions = sorted(result.order.index(i) for i in range(4))
    # No two colours are adjacent in the resulting order.
    assert all(b - a > 1 for a, b in zip(colour_positions, colour_positions[1:]))


def test_synonyms_are_treated_as_high_risk():
    candidates = [_node(0, "borrow", synonyms=("lend",)), _node(1, "lend"), _node(2, "table")]

    result = order_for_diversity(candidates)

    assert result.order.index(1) != result.order.index(0) + 1 or result.order.index(0) != result.order.index(1) + 1


def test_antonyms_are_treated_as_high_risk():
    candidates = [_node(0, "hot", antonyms=("cold",)), _node(1, "cold"), _node(2, "table")]

    result = order_for_diversity(candidates)

    positions = {result.order[i]: i for i in range(len(result.order))}
    assert abs(positions[0] - positions[1]) > 1


def test_collocations_alone_are_not_treated_as_high_risk():
    """TODO 1: collocates are thematically, not semantically, related."""
    candidates = [_node(0, "make", collocations=("a decision",)), _node(1, "a decision")]

    result = order_for_diversity(candidates)

    # With no synonym/antonym/topic edge between them, nothing forces
    # separation — the input order is preserved.
    assert result.order == [0, 1]


def test_a_candidate_overlapping_recently_studied_vocabulary_is_deferred():
    """TODO 2: the constraint extends past today's batch."""
    candidates = [_node(0, "puppy", topics=("animals",)), _node(1, "table")]
    recently_studied = [_node(100, "kitten", topics=("animals",))]

    result = order_for_diversity(candidates, recently_studied=recently_studied)

    assert result.deferred_for_recent_study == {0}
    assert result.order[-1] == 0  # deferred candidates land at the end


def test_recently_studied_vocabulary_never_appears_in_the_output_order():
    candidates = [_node(0, "puppy", topics=("animals",))]
    recently_studied = [_node(100, "kitten", topics=("animals",))]

    result = order_for_diversity(candidates, recently_studied=recently_studied)

    assert 100 not in result.order
    assert set(result.order) == {0}


def test_an_empty_batch_returns_an_empty_order():
    result = order_for_diversity([])

    assert result.order == []
    assert result.deferred_for_recent_study == frozenset()


def test_a_batch_too_uniform_to_fully_separate_still_returns_every_index_exactly_once():
    """Pigeonhole: four colours and only one filler cannot be fully spread
    apart (that needs 3 gaps, this batch has 1) — the algorithm must still
    terminate cleanly rather than lose or duplicate an item."""
    candidates = [
        _node(0, "red", topics=("colours",)),
        _node(1, "blue", topics=("colours",)),
        _node(2, "green", topics=("colours",)),
        _node(3, "yellow", topics=("colours",)),
        _node(4, "table"),
    ]

    result = order_for_diversity(candidates)

    assert sorted(result.order) == [0, 1, 2, 3, 4]


def test_ordering_is_deterministic():
    candidates = [
        _node(0, "red", topics=("colours",)),
        _node(1, "blue", topics=("colours",)),
        _node(2, "table"),
        _node(3, "run"),
    ]

    assert order_for_diversity(candidates).order == order_for_diversity(candidates).order
