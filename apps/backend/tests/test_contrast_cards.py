"""Contract tests for issue #206's presentation-only contrast cards."""

from datetime import datetime, timezone

import pytest

from app.domain.entities import Word
from app.domain.services.contrast_cards import (
    ContrastCard,
    InterventionPairDecision,
    answer_contrast_card,
    build_contrast_cards,
)
from app.domain.services.knowledge_graph import KnowledgeEdge, KnowledgeGraph, Relation, WordNode
from app.domain.value_objects import ReviewState, SupportedLanguage


NOW = datetime(2026, 8, 6, tzinfo=timezone.utc).replace(tzinfo=None)


def _word(word_id: int, term: str, *, stability: float | None = 30.0, repetitions: int = 3) -> Word:
    return Word(
        id=word_id,
        group_id=1,
        term=term,
        target_language=SupportedLanguage.ENGLISH,
        review_state=ReviewState(
            strength=90,
            ease_factor=2.5,
            interval_days=30,
            repetitions=repetitions,
            due_at=NOW,
            last_reviewed_at=NOW,
            stability=stability,
        ),
    )


def _graph(*edges: KnowledgeEdge) -> KnowledgeGraph:
    return KnowledgeGraph(
        [WordNode(1, "borrow"), WordNode(2, "lend"), WordNode(3, "take")],
        list(edges),
    )


def test_contrast_card_is_one_adjacent_pair_with_a_relational_prompt():
    cards = build_contrast_cards(
        [_word(1, "borrow"), _word(2, "lend")],
        _graph(KnowledgeEdge(1, 2, Relation.ANTONYM, "listed as an antonym")),
        enabled=True,
    )

    assert len(cards) == 1
    assert cards[0].word_ids == (1, 2)
    assert cards[0].prompt == "How does borrow differ from lend?"
    assert len(cards[0].word_ids) == 2  # no filler can be inserted in the card


def test_new_and_learning_words_never_receive_a_card_at_the_conservative_threshold():
    graph = _graph(KnowledgeEdge(1, 2, Relation.SYNONYM, "listed as a synonym"))

    assert build_contrast_cards([_word(1, "a", stability=None), _word(2, "b")], graph, enabled=True) == ()
    assert build_contrast_cards([_word(1, "a", stability=30, repetitions=0), _word(2, "b")], graph, enabled=True) == ()
    assert build_contrast_cards([_word(1, "a", stability=10), _word(2, "b")], graph, enabled=True) == ()


def test_threshold_is_configurable_and_feature_is_off_by_default():
    graph = _graph(KnowledgeEdge(1, 2, Relation.SYNONYM, "listed as a synonym"))
    words = [_word(1, "a", stability=10), _word(2, "b", stability=11)]

    assert build_contrast_cards(words, graph, enabled=False, minimum_stability=1) == ()
    cards = build_contrast_cards(words, graph, enabled=True, minimum_stability=10)
    assert len(cards) == 1


def test_isolate_decision_wins_over_graph_suggestion():
    graph = _graph(KnowledgeEdge(1, 2, Relation.SYNONYM, "listed as a synonym"))
    decision = InterventionPairDecision(1, 2, "isolate")

    assert build_contrast_cards(
        [_word(1, "a"), _word(2, "b")],
        graph,
        enabled=True,
        intervention_decisions=(decision,),
    ) == ()


def test_contrast_decision_is_preferred_to_graph_fallback():
    graph = _graph(KnowledgeEdge(1, 2, Relation.SYNONYM, "listed as a synonym"))
    cards = build_contrast_cards(
        [_word(1, "a"), _word(2, "b")],
        graph,
        enabled=True,
        intervention_decisions=(InterventionPairDecision(2, 1, "contrast"),),
    )

    assert cards[0].word_ids == (1, 2)


def test_answer_requires_both_word_notes_and_never_changes_review_state():
    card = ContrastCard((1, 2), ("borrow", "lend"), Relation.ANTONYM, "How does borrow differ from lend?")
    before = _word(1, "borrow").review_state
    answer = answer_contrast_card(
        card,
        first_word_note="receive temporarily",
        second_word_note="give temporarily",
        distinction="the direction of transfer differs",
        answered_at=NOW,
    )

    assert answer.card is card
    assert _word(1, "borrow").review_state == before
    with pytest.raises(ValueError):
        answer_contrast_card(
            card,
            first_word_note="",
            second_word_note="give temporarily",
            distinction="direction",
            answered_at=NOW,
        )
