"""Mistake memory and weakness detection (issue #134, split from #77).

The thing worth guarding against is confident nonsense: three wrong answers on
a Tuesday becoming "you struggle with irregular verbs", which the learner then
believes and studies. So most of these tests are about the profile declining
to claim things.
"""
from __future__ import annotations

import pytest

from app.domain.services.knowledge_graph import KnowledgeGraph, Relation, WordNode, build_edges
from app.domain.services.weakness import (
    MIN_CONFUSIONS_FOR_PAIR,
    MIN_OCCURRENCES_FOR_CATEGORY,
    MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE,
    ErrorCategory,
    MistakeEvent,
    WeaknessProfileService,
    categorise,
    cross_association_report,
)


def _events(category: ErrorCategory, count: int, word_id: int = 1) -> list[MistakeEvent]:
    return [MistakeEvent(user_id=1, word_id=word_id, category=category) for _ in range(count)]


def _confusion(word_id: int, other: int, count: int) -> list[MistakeEvent]:
    return [
        MistakeEvent(
            user_id=1,
            word_id=word_id,
            category=ErrorCategory.WRONG_WORD,
            confused_with_word_id=other,
        )
        for _ in range(count)
    ]


# --- Declining to claim things ---------------------------------------------


def test_no_history_is_reported_as_not_knowing_yet():
    """Not as an empty profile, which reads as "you have no weaknesses"."""
    profile = WeaknessProfileService.build([])

    assert profile.insufficient_data is True
    assert profile.categories == []


def test_a_category_below_the_threshold_is_not_named():
    """A learner told they are weak at something after two slips will either
    dismiss the feature or, worse, believe it."""
    profile = WeaknessProfileService.build(
        _events(ErrorCategory.SPELLING, MIN_OCCURRENCES_FOR_CATEGORY - 1)
    )

    assert profile.categories == []
    assert profile.insufficient_data is True


def test_mistakes_that_are_too_scattered_to_name_still_count():
    """The total is real even when nothing crosses the threshold — the profile
    knows there were mistakes, just not what they mean."""
    events = _events(ErrorCategory.SPELLING, 1) + _events(ErrorCategory.SENSE, 1)

    profile = WeaknessProfileService.build(events)

    assert profile.total_mistakes == 2
    assert profile.insufficient_data is True


def test_a_single_confusion_is_a_slip_not_a_pattern():
    profile = WeaknessProfileService.build(_confusion(1, 2, MIN_CONFUSIONS_FOR_PAIR - 1))

    assert profile.confused_pairs == []


# --- Naming what is real ---------------------------------------------------


def test_a_repeated_category_is_reported_with_its_count():
    profile = WeaknessProfileService.build(_events(ErrorCategory.INFLECTION, 4))

    assert profile.categories[0].category is ErrorCategory.INFLECTION
    assert profile.categories[0].occurrences == 4


def test_the_share_is_carried_alongside_the_count_not_instead_of_it():
    """60% of five mistakes and 60% of five hundred are very different
    claims."""
    events = _events(ErrorCategory.SPELLING, 6) + _events(ErrorCategory.SENSE, 4)

    profile = WeaknessProfileService.build(events)

    top = profile.categories[0]
    assert top.occurrences == 6
    assert top.share == pytest.approx(0.6)


def test_categories_are_ordered_by_frequency():
    events = _events(ErrorCategory.SPELLING, 3) + _events(ErrorCategory.SENSE, 7)

    profile = WeaknessProfileService.build(events)

    assert [c.category for c in profile.categories] == [
        ErrorCategory.SENSE,
        ErrorCategory.SPELLING,
    ]


def test_equal_counts_have_a_stable_order():
    """Otherwise the profile reshuffles between requests for no reason the
    learner can see."""
    events = _events(ErrorCategory.SPELLING, 3) + _events(ErrorCategory.SENSE, 3)

    first = WeaknessProfileService.build(events)
    second = WeaknessProfileService.build(list(reversed(events)))

    assert [c.category for c in first.categories] == [c.category for c in second.categories]


def test_only_the_top_categories_are_reported():
    """A profile listing everything gives no sense of priority."""
    events: list[MistakeEvent] = []
    for category in ErrorCategory:
        events.extend(_events(category, 5))

    profile = WeaknessProfileService.build(events, top_categories=2)

    assert len(profile.categories) == 2


# --- Confused pairs --------------------------------------------------------


def test_a_repeated_confusion_becomes_a_pair():
    profile = WeaknessProfileService.build(_confusion(1, 2, MIN_CONFUSIONS_FOR_PAIR))

    assert profile.confused_pairs[0].occurrences == MIN_CONFUSIONS_FOR_PAIR


def test_a_pair_is_the_same_pair_in_either_direction():
    """A learner who confused them both ways would otherwise see two entries
    describing one problem."""
    events = _confusion(1, 2, 1) + _confusion(2, 1, 1)

    profile = WeaknessProfileService.build(events)

    assert len(profile.confused_pairs) == 1
    assert profile.confused_pairs[0].occurrences == 2


def test_a_word_confused_with_itself_is_dropped():
    """That is a recording bug, not a pattern."""
    profile = WeaknessProfileService.build(_confusion(1, 1, 5))

    assert profile.confused_pairs == []


def test_pairs_are_ordered_by_frequency():
    events = _confusion(1, 2, 2) + _confusion(3, 4, 5)

    profile = WeaknessProfileService.build(events)

    assert profile.confused_pairs[0].word_id == 3


# --- Classifying one wrong answer ------------------------------------------


def test_a_skipped_answer_is_not_recalled_rather_than_wrong():
    """Usually means never learned rather than mislearned, and the remedy
    differs."""
    category, confused = categorise("skipped", None, "gato")

    assert category is ErrorCategory.NOT_RECALLED
    assert confused is None


def test_an_empty_answer_is_treated_as_not_recalled():
    assert categorise("incorrect", "   ", "gato")[0] is ErrorCategory.NOT_RECALLED


def test_answering_with_another_word_the_learner_studies_names_the_confusion():
    category, confused = categorise("incorrect", "perro", "gato", {"perro": 7})

    assert category is ErrorCategory.WRONG_WORD
    assert confused == 7


def test_a_misspelling_that_resembles_a_word_is_not_called_a_confusion():
    """Only an attempt that *is* another word they are learning counts. A
    random typo resembling one is not evidence of confusing the two."""
    category, confused = categorise("incorrect", "gatoo", "gato", {"perro": 7})

    assert category is ErrorCategory.SPELLING
    assert confused is None


def test_a_near_miss_is_a_spelling_error():
    assert categorise("incorrect", "recieve", "receive")[0] is ErrorCategory.SPELLING


def test_something_unrecognisable_is_unknown_rather_than_guessed():
    """A classifier that guesses produces a profile that guesses, and the
    learner cannot tell the difference."""
    assert categorise("incorrect", "xyzzy", "gato")[0] is ErrorCategory.UNKNOWN


def test_an_answer_identical_to_the_target_is_not_filed_as_a_learner_error():
    """Marked wrong but textually identical — a grader disagreement or a
    trailing-space artefact."""
    assert categorise("incorrect", " gato ", "gato")[0] is ErrorCategory.UNKNOWN


def test_classification_ignores_case():
    category, confused = categorise("incorrect", "Perro", "gato", {"perro": 7})

    assert category is ErrorCategory.WRONG_WORD
    assert confused == 7


# --- One derivation, not two (issue #207) -----------------------------------


def test_confusion_pair_counts_agrees_with_the_knowledge_graphs_confusions():
    """`ConfusedPair` (this module) and the knowledge graph's `CONFUSED_WITH`
    edges (`app/application/use_cases/knowledge_graph.py`) both derive from
    the same mistake log. This asserts they agree on the underlying counts
    for the same data, not just that each looks reasonable on its own."""
    from app.application.use_cases.knowledge_graph import confusions_for
    from app.domain.services.weakness import confusion_pair_counts

    class _Row:
        def __init__(self, word_id: int, confused_with_word_id: int | None, occurrence_count: int = 1):
            self.word_id = word_id
            self.confused_with_word_id = confused_with_word_id
            self.occurrence_count = occurrence_count

    class _MistakeRepo:
        def __init__(self, rows: list[_Row]):
            self._rows = rows

        def list_for_user(self, user_id: int) -> list[_Row]:
            return self._rows

    rows = [_Row(1, 2), _Row(1, 2), _Row(2, 1), _Row(3, 3), _Row(4, None)]
    events = [
        MistakeEvent(user_id=1, word_id=r.word_id, category=ErrorCategory.WRONG_WORD, confused_with_word_id=r.confused_with_word_id)
        for r in rows
    ]

    from_weakness = confusion_pair_counts((e.word_id, e.confused_with_word_id, 1) for e in events)
    from_graph = confusions_for(_MistakeRepo(rows), user_id=1)

    assert from_weakness == from_graph == {(1, 2): 3}


# --- Cross-association error rate (issue #207 TODO 0) -----------------------


def _cross_association_graph() -> KnowledgeGraph:
    """1 (borrow) is a synonym of 2 (lend), shares a topic with 4 (loan), and
    shares neither with 3 (table) — a pure control."""
    nodes = [
        WordNode(word_id=1, term="borrow", synonyms=("lend",), topics=("finance",)),
        WordNode(word_id=2, term="lend"),
        WordNode(word_id=3, term="table"),
        WordNode(word_id=4, term="loan", topics=("finance",)),
    ]
    edges = build_edges(nodes, confusions={(1, 2): 1, (1, 3): 1})
    return KnowledgeGraph(nodes, edges)


def test_a_fixture_deck_produces_a_known_cross_association_rate():
    """The issue's own verify criterion for TODO 0: a fixture deck with a
    known composition produces an exactly predictable rate."""
    graph = _cross_association_graph()
    events = [
        *[MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=2) for _ in range(3)],
        *[MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=3) for _ in range(2)],
        *[MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=4) for _ in range(3)],
    ]

    report = cross_association_report(events, graph)

    assert report.resolved_errors == 8
    assert report.related_errors == 6  # the 3 synonym confusions + the 3 topic confusions
    assert report.error_rate == 0.75
    assert not report.insufficient_data
    assert {r.relation: r.occurrences for r in report.by_relation} == {
        Relation.SYNONYM: 3,
        Relation.TOPIC: 3,
    }


def test_being_previously_confused_alone_does_not_count_as_related():
    """1 and 3 share no lexical/topic relation — only a CONFUSED_WITH edge
    from the `confusions=` map in the fixture graph above. If CONFUSED_WITH
    counted toward the rate, this would trivially become "related" for
    having been confused, which is circular: that edge is itself derived
    from this same mistake log."""
    graph = _cross_association_graph()
    events = [
        MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=3)
        for _ in range(MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE)
    ]

    report = cross_association_report(events, graph)

    assert report.related_errors == 0
    assert report.error_rate == 0.0
    assert report.by_relation == []


def test_below_the_minimum_sample_reports_insufficient_data_not_a_rate():
    graph = _cross_association_graph()
    events = [
        MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=2)
        for _ in range(MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE - 1)
    ]

    report = cross_association_report(events, graph)

    assert report.insufficient_data
    assert report.error_rate == 0.0


def test_unresolved_mistakes_are_excluded_from_the_denominator():
    """A typo or a skip cannot be checked against the graph at all — it
    should not silently count as a non-related error and dilute the rate."""
    graph = _cross_association_graph()
    events = [
        *[MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=2) for _ in range(5)],
        *[MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.NOT_RECALLED) for _ in range(20)],
    ]

    report = cross_association_report(events, graph)

    assert report.resolved_errors == 5


def test_a_pair_related_more_than_one_way_still_counts_once_toward_related_errors():
    nodes = [
        WordNode(word_id=1, term="gato", synonyms=("minino",), topics=("animals",)),
        WordNode(word_id=2, term="minino", topics=("animals",)),
    ]
    graph = KnowledgeGraph(nodes, build_edges(nodes))
    events = [
        MistakeEvent(user_id=1, word_id=1, category=ErrorCategory.WRONG_WORD, confused_with_word_id=2)
        for _ in range(MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE)
    ]

    report = cross_association_report(events, graph)

    assert report.related_errors == MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE
    assert report.error_rate == 1.0
    assert {r.relation for r in report.by_relation} == {Relation.SYNONYM, Relation.TOPIC}
