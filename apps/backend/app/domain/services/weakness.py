"""What a learner keeps getting wrong, and how confident we are that it's real
(issue #134, split from #77).

A weakness profile is easy to make and easy to make badly. The failure mode is
confident nonsense: three wrong answers on a Tuesday become "you struggle with
irregular verbs", the learner believes it, and studies the wrong thing. So
this errs the other way — categories need repetition before they are reported,
confused pairs need to have actually been confused more than once, and
everything carries the count it was derived from.

Pure and deterministic. It takes mistake events and returns a profile; it does
not query, and it does not ask a model what the learner is bad at.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable

from app.domain.services.knowledge_graph import KnowledgeGraph, Relation

# A category needs this many occurrences before it is named. Below it, the
# honest answer is that there is not enough evidence — a learner told they are
# weak at something after two slips will either dismiss the feature or, worse,
# believe it.
MIN_OCCURRENCES_FOR_CATEGORY = 3

# A pair of words needs this many mutual confusions before being called
# confusable. Once is a slip; twice is a pattern worth showing.
MIN_CONFUSIONS_FOR_PAIR = 2

# Most-frequent categories reported. A profile listing everything is a list
# nobody reads and gives no sense of priority.
TOP_CATEGORIES = 5

# Resolved errors needed before a cross-association rate is reported, for the
# same reason MIN_OCCURRENCES_FOR_CATEGORY exists: a rate computed from two
# or three answers is noise dressed up as a finding.
MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE = 5

# Relations checked when deciding whether a wrong answer was semantically
# related to the target. Deliberately excludes CONFUSED_WITH: that edge is
# itself derived from this same mistake log (RecomputeKnowledgeEdgesForWordUseCase),
# so including it would make the rate trivially ~100% instead of testing
# whether *pre-existing* relatedness (synonym, antonym, shared topic,
# collocation) predicts which wrong answer gets chosen — issue #207's actual
# question.
CROSS_ASSOCIATION_RELATIONS = (Relation.SYNONYM, Relation.ANTONYM, Relation.TOPIC, Relation.COLLOCATION)


class ErrorCategory(str, Enum):
    """The kind of mistake, at the granularity a learner can act on.

    Deliberately coarse and closed. "You confuse perfective and imperfective
    aspect" is actionable; "token-level edit distance 2" is not, and a category
    set that grows freely ends up describing the data rather than the learner.
    """

    # Answered with a different word entirely — the interesting one, because it
    # names a specific confusion rather than a general weakness.
    WRONG_WORD = "wrong_word"
    SPELLING = "spelling"
    # Right meaning, wrong form: tense, case, agreement.
    INFLECTION = "inflection"
    # Right word, wrong sense for the context.
    SENSE = "sense"
    # No answer given. Distinct from a wrong one: it usually means never
    # learned rather than mislearned, and the remedy differs.
    NOT_RECALLED = "not_recalled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MistakeEvent:
    """One recorded error. Immutable — history, not state."""

    user_id: int
    word_id: int
    category: ErrorCategory
    attempted_answer: str | None = None
    # The word the learner appears to have answered with, when their attempt
    # matched another word they are learning. This is what makes a confusion
    # pair, and it is only ever set from real vocabulary rather than guessed.
    confused_with_word_id: int | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class CategoryWeakness:
    category: ErrorCategory
    occurrences: int
    # Share of all this learner's mistakes. Carried alongside the count rather
    # than instead of it: 60% of five mistakes and 60% of five hundred are very
    # different claims.
    share: float


@dataclass(frozen=True)
class ConfusedPair:
    """Two words the learner mixes up, in a stable order.

    Ordered by id so (gato, gata) and (gata, gato) are the same pair. Without
    that, a learner who confused them in both directions would see two entries
    describing one problem.
    """

    word_id: int
    confused_with_word_id: int
    occurrences: int


@dataclass
class WeaknessProfile:
    total_mistakes: int = 0
    categories: list[CategoryWeakness] = field(default_factory=list)
    confused_pairs: list[ConfusedPair] = field(default_factory=list)
    # Set when there is not enough history to say anything. The caller shows
    # this instead of an empty profile, which reads as "you have no weaknesses"
    # rather than "we do not know yet".
    insufficient_data: bool = False


class WeaknessProfileService:
    """Stateless. Aggregates mistake events into something a learner can use."""

    @staticmethod
    def build(
        events: list[MistakeEvent],
        min_occurrences: int = MIN_OCCURRENCES_FOR_CATEGORY,
        min_confusions: int = MIN_CONFUSIONS_FOR_PAIR,
        top_categories: int = TOP_CATEGORIES,
    ) -> WeaknessProfile:
        if not events:
            return WeaknessProfile(insufficient_data=True)

        total = len(events)
        counts = Counter(event.category for event in events)

        categories = [
            CategoryWeakness(category=category, occurrences=count, share=count / total)
            for category, count in counts.items()
            if count >= min_occurrences
        ]
        # Sorted by count, then by category name so equal counts have a stable
        # order rather than one that depends on Counter's insertion order.
        categories.sort(key=lambda c: (-c.occurrences, c.category.value))

        profile = WeaknessProfile(
            total_mistakes=total,
            categories=categories[:top_categories],
            confused_pairs=_confused_pairs(events, min_confusions),
        )
        # Enough mistakes to count, but none frequent enough to name. Reported
        # as insufficient rather than as an empty list, which would read as
        # "nothing is wrong".
        profile.insufficient_data = not profile.categories and not profile.confused_pairs
        return profile


def confusion_pair_counts(observations: Iterable[tuple[int, int | None, int]]) -> dict[tuple[int, int], int]:
    """Group raw (word_id, confused_with_word_id, weight) observations into
    unordered-pair counts.

    The one derivation both `ConfusedPair` here and the knowledge graph's
    `CONFUSED_WITH` edges (`app/application/use_cases/knowledge_graph.py`)
    are built from — previously computed twice, independently, from the same
    mistake log (issue #207). A word "confused with itself" is a recording
    bug, not a pattern, so it's dropped here rather than in each caller.
    """
    pairs: dict[tuple[int, int], int] = defaultdict(int)
    for word_id, confused_with_word_id, weight in observations:
        if confused_with_word_id is None or confused_with_word_id == word_id:
            continue
        key = (min(word_id, confused_with_word_id), max(word_id, confused_with_word_id))
        pairs[key] += weight
    return dict(pairs)


@dataclass(frozen=True)
class RelationErrorCount:
    relation: Relation
    occurrences: int


@dataclass(frozen=True)
class CrossAssociationReport:
    """How often a wrong answer was, independent of the mistake log itself, a
    word already known to be semantically related to the target.

    This is the one dependent measure that survives well-controlled studies
    in the literature behind the Semantic Relatedness track (issue #207):
    within-set confusion rate, not immediate recall score. `resolved_errors`
    is the denominator — wrong answers that named another word this learner
    actually studies, per `MistakeEvent.confused_with_word_id` — not every
    mistake, since an unresolved wrong answer (a typo, a blank) cannot be
    checked against the graph at all.
    """

    resolved_errors: int
    related_errors: int
    error_rate: float
    by_relation: list[RelationErrorCount] = field(default_factory=list)
    insufficient_data: bool = False


def cross_association_report(
    events: list[MistakeEvent],
    graph: KnowledgeGraph,
    minimum: int = MIN_RESOLVED_ERRORS_FOR_CROSS_ASSOCIATION_RATE,
) -> CrossAssociationReport:
    """Segment resolved wrong answers by whether the chosen word was already
    semantically related to the target, and by which relation (issue #207
    TODO 0). A pair can hold more than one relation at once (a shared topic
    *and* a synonym), so one error can contribute to more than one bucket in
    `by_relation` — `related_errors` still counts it once.
    """
    resolved = [
        event
        for event in events
        if event.confused_with_word_id is not None and event.confused_with_word_id != event.word_id
    ]
    if len(resolved) < minimum:
        return CrossAssociationReport(resolved_errors=len(resolved), related_errors=0, error_rate=0.0, insufficient_data=True)

    relation_counts: Counter[Relation] = Counter()
    related_errors = 0
    checked_relations = set(CROSS_ASSOCIATION_RELATIONS)
    for event in resolved:
        relations = graph.relations_between(event.word_id, event.confused_with_word_id) & checked_relations
        if relations:
            related_errors += 1
            relation_counts.update(relations)

    by_relation = [
        RelationErrorCount(relation=relation, occurrences=count) for relation, count in relation_counts.items()
    ]
    by_relation.sort(key=lambda r: (-r.occurrences, r.relation.value))

    return CrossAssociationReport(
        resolved_errors=len(resolved),
        related_errors=related_errors,
        error_rate=related_errors / len(resolved),
        by_relation=by_relation,
        insufficient_data=False,
    )


def _confused_pairs(events: list[MistakeEvent], minimum: int) -> list[ConfusedPair]:
    counts = confusion_pair_counts((event.word_id, event.confused_with_word_id, 1) for event in events)

    found = [
        ConfusedPair(word_id=a, confused_with_word_id=b, occurrences=count)
        for (a, b), count in counts.items()
        if count >= minimum
    ]
    found.sort(key=lambda p: (-p.occurrences, p.word_id, p.confused_with_word_id))
    return found


def categorise(
    outcome: str, attempted: str | None, expected: str, known_terms: dict[str, int] | None = None
) -> tuple[ErrorCategory, int | None]:
    """Classify one wrong answer, and name the word it was confused with.

    Deliberately conservative and rule-based rather than a model call. A
    classifier that guesses produces a weakness profile that guesses, and the
    learner cannot tell the difference — so anything unclear becomes UNKNOWN
    rather than a plausible-sounding category.

    `known_terms` maps the learner's own vocabulary to word ids. A confusion is
    only recorded when the attempt *is* another word they are actually
    learning; a random misspelling that happens to resemble one is not evidence
    of confusing the two.
    """
    if outcome == "skipped" or not attempted or not attempted.strip():
        return ErrorCategory.NOT_RECALLED, None

    attempt = attempted.strip().casefold()
    target = expected.strip().casefold()

    if attempt == target:
        # Marked wrong but textually identical — a grader disagreement or a
        # trailing-whitespace artefact, not a learner error to file away.
        return ErrorCategory.UNKNOWN, None

    if known_terms:
        matched = known_terms.get(attempt)
        if matched is not None:
            return ErrorCategory.WRONG_WORD, matched

    if _is_near_miss(attempt, target):
        return ErrorCategory.SPELLING, None

    return ErrorCategory.UNKNOWN, None


def _is_near_miss(attempt: str, target: str) -> bool:
    """Whether the attempt is a small typo of the target.

    A cheap edit-distance bound rather than a real metric: enough to separate
    "recieve" from a completely different word, and not enough to pretend it
    understands morphology. Anything subtler is left as UNKNOWN, which is the
    honest answer.
    """
    if abs(len(attempt) - len(target)) > 2:
        return False
    longer, shorter = (attempt, target) if len(attempt) >= len(target) else (target, attempt)
    if longer.startswith(shorter) or longer.endswith(shorter):
        return True
    differences = sum(1 for a, b in zip(attempt, target) if a != b)
    differences += abs(len(attempt) - len(target))
    return differences <= 2
