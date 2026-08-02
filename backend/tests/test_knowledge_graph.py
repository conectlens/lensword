"""The personal knowledge graph (issue #138, split from #77).

Words already carry synonyms, antonyms, topics and collocations as free text.
The thing being tested is the step that makes them useful: turning a string
into a relation between two cards the learner actually owns, and refusing to
when there is no second card.
"""
from __future__ import annotations

import pytest

from app.domain.services.knowledge_graph import (
    RELATION_WEIGHT,
    KnowledgeGraph,
    Relation,
    WordNode,
    build_edges,
)


def _node(word_id: int, term: str, **kwargs) -> WordNode:
    return WordNode(word_id=word_id, term=term, **kwargs)


# --- Edges only join words the learner has ---------------------------------


def test_a_synonym_pointing_at_an_owned_word_becomes_an_edge():
    nodes = [_node(1, "gato", synonyms=("minino",)), _node(2, "minino")]

    edges = build_edges(nodes)

    assert len(edges) == 1
    assert edges[0].relation is Relation.SYNONYM


def test_a_synonym_the_learner_does_not_study_produces_nothing():
    """An edge to a word they do not have is an edge to nothing — a graph full
    of dangling references that looks rich and answers nothing."""
    edges = build_edges([_node(1, "gato", synonyms=("minino",))])

    assert edges == []


def test_a_word_listed_as_its_own_synonym_is_ignored():
    """A data-entry slip, not a relation."""
    assert build_edges([_node(1, "gato", synonyms=("gato",))]) == []


def test_matching_ignores_case_and_surrounding_space():
    nodes = [_node(1, "gato", synonyms=("  Minino ",)), _node(2, "minino")]

    assert len(build_edges(nodes)) == 1


# --- One relation is one edge ----------------------------------------------


def test_a_relation_asserted_from_both_ends_is_a_single_edge():
    """Deriving it twice must not produce two edges describing one fact."""
    nodes = [_node(1, "gato", synonyms=("minino",)), _node(2, "minino", synonyms=("gato",))]

    edges = build_edges(nodes)

    assert len(edges) == 1


def test_edges_are_stored_with_the_lower_id_first():
    nodes = [_node(7, "gato", synonyms=("minino",)), _node(2, "minino")]

    edge = build_edges(nodes)[0]

    assert (edge.source_id, edge.target_id) == (2, 7)


def test_two_words_can_hold_more_than_one_kind_of_relation():
    """Sharing a topic and being confused with each other are different facts
    about the same pair, and collapsing them would lose one."""
    nodes = [
        _node(1, "gato", topics=("animals",)),
        _node(2, "perro", topics=("animals",)),
    ]

    edges = build_edges(nodes, confusions={(1, 2): 3})

    assert {e.relation for e in edges} == {Relation.TOPIC, Relation.CONFUSED_WITH}


# --- Topics ----------------------------------------------------------------


def test_words_sharing_a_topic_are_joined():
    nodes = [
        _node(1, "gato", topics=("animals",)),
        _node(2, "perro", topics=("animals",)),
        _node(3, "mesa", topics=("furniture",)),
    ]

    edges = build_edges(nodes)

    assert len(edges) == 1
    assert {edges[0].source_id, edges[0].target_id} == {1, 2}


def test_an_enormous_topic_is_skipped_rather_than_exploded():
    """A learner who tags four hundred words "general" would otherwise
    generate eighty thousand edges that say nothing."""
    nodes = [_node(i, f"w{i}", topics=("general",)) for i in range(1, 60)]

    assert build_edges(nodes) == []


def test_a_topic_with_one_member_produces_no_edge():
    assert build_edges([_node(1, "gato", topics=("animals",))]) == []


# --- Strength is evidence, not opinion -------------------------------------


def test_confusion_outranks_a_typed_label():
    """Observed behaviour beats something someone filed. A word you keep mixing
    up is more urgent than one you tagged with the same topic."""
    assert RELATION_WEIGHT[Relation.CONFUSED_WITH] > RELATION_WEIGHT[Relation.TOPIC]
    assert RELATION_WEIGHT[Relation.SYNONYM] > RELATION_WEIGHT[Relation.TOPIC]


def test_repetition_raises_strength_with_diminishing_returns():
    """A pair confused ten times is not ten times more urgent than one confused
    twice, and letting repetition dominate would bury a strong-but-single
    relation under a weak-but-frequent one."""
    edges = build_edges([_node(1, "a"), _node(2, "b")], confusions={(1, 2): 20})

    assert edges[0].strength == RELATION_WEIGHT[Relation.CONFUSED_WITH] * 2


def test_every_edge_can_say_why_it_exists():
    """A graph that cannot justify an edge is one nobody trusts enough to act
    on."""
    nodes = [_node(1, "gato", synonyms=("minino",)), _node(2, "minino")]

    assert "synonym" in build_edges(nodes)[0].evidence


def test_confusion_evidence_states_the_count():
    edges = build_edges([_node(1, "a"), _node(2, "b")], confusions={(1, 2): 4})

    assert "4 time(s)" in edges[0].evidence


def test_a_word_confused_with_itself_is_dropped():
    assert build_edges([_node(1, "a")], confusions={(1, 1): 5}) == []


def test_edges_are_ordered_strongest_first():
    nodes = [
        _node(1, "gato", topics=("animals",), synonyms=("minino",)),
        _node(2, "minino", topics=("animals",)),
    ]

    edges = build_edges(nodes)

    assert edges[0].relation is Relation.SYNONYM


# --- Queries ---------------------------------------------------------------


@pytest.fixture()
def graph() -> KnowledgeGraph:
    nodes = [
        _node(1, "gato", topics=("animals",), cefr_level="B1"),
        _node(2, "perro", topics=("animals",), cefr_level="A1"),
        _node(3, "minino", cefr_level="C1"),
        _node(4, "mesa", topics=("furniture",), cefr_level=None),
    ]
    edges = build_edges(nodes, confusions={(1, 2): 3, (1, 3): 1})
    return KnowledgeGraph(nodes, edges)


def test_related_returns_everything_touching_a_word(graph):
    related = graph.related(1)

    assert related
    assert all(1 in (e.source_id, e.target_id) for e in related)


def test_confused_with_returns_only_confusions(graph):
    confused = graph.confused_with(1)

    assert confused
    assert all(e.relation is Relation.CONFUSED_WITH for e in confused)


def test_topic_words_lists_the_members(graph):
    assert graph.topic_words("animals") == [1, 2]


def test_topic_lookup_ignores_case(graph):
    assert graph.topic_words("ANIMALS") == [1, 2]


def test_prerequisites_are_strictly_easier_related_words(graph):
    """"What should I learn before this?" A related word at the same level is
    not a prerequisite."""
    assert graph.prerequisites(1) == [2]


def test_a_word_with_no_level_recorded_is_not_a_prerequisite(graph):
    """Unknown is different from easy, and including it would answer the
    question with a guess."""
    assert 4 not in graph.prerequisites(1)


def test_a_word_whose_own_level_is_unknown_has_no_prerequisites(graph):
    assert graph.prerequisites(4) == []


def test_an_unknown_word_is_handled_rather_than_raising(graph):
    assert graph.prerequisites(9999) == []
    assert graph.related(9999) == []
