"""Stability-gated contrast cards (issue #206).

Contrast is a presentation format, not a second scheduler.  A card carries
two already-established words and asks the learner to discriminate between
them.  Rendering or answering one therefore has no path to ``ReviewState``
or ``due_at``.

The candidate builder is pure and deterministic.  It accepts an optional
intervention decision from the diagnosis planner; otherwise it falls back to
the strongest synonym/antonym edges in the learner's own graph.  An isolate
decision always wins over a graph suggestion, so this mechanism cannot undo a
diagnosis-driven safety decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.entities import Word
from app.domain.services.knowledge_graph import KnowledgeGraph, Relation

DEFAULT_MIN_STABILITY_DAYS = 21.0
MAX_CONTRAST_CARDS = 20
CONTRAST_RELATIONS = frozenset({Relation.SYNONYM, Relation.ANTONYM})


@dataclass(frozen=True, slots=True)
class InterventionPairDecision:
    """A planner decision for a pair, kept separate from card rendering."""

    first_word_id: int
    second_word_id: int
    strategy: str

    def pair(self) -> frozenset[int]:
        return frozenset((self.first_word_id, self.second_word_id))


@dataclass(frozen=True, slots=True)
class ContrastCard:
    """One adjacent, relational prompt.

    ``word_ids`` is exactly two items.  Keeping the pair on one value object
    makes adjacency structural: a caller cannot insert a filler item between
    the target and its competitor without constructing a different card.
    """

    word_ids: tuple[int, int]
    terms: tuple[str, str]
    relation: Relation
    prompt: str

    def __post_init__(self) -> None:
        if len(self.word_ids) != 2 or self.word_ids[0] == self.word_ids[1]:
            raise ValueError("A contrast card must contain two distinct word ids")
        if len(self.terms) != 2 or any(not term.strip() for term in self.terms):
            raise ValueError("A contrast card must contain two non-empty terms")
        expected = f"How does {self.terms[0]} differ from {self.terms[1]}?"
        if self.prompt != expected:
            raise ValueError("Contrast cards must use the relational difference prompt")


@dataclass(frozen=True, slots=True)
class ContrastAnswer:
    """A contrast response; it is evidence for the card, not an FSRS review."""

    card: ContrastCard
    first_word_note: str
    second_word_note: str
    distinction: str
    answered_at: datetime

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.first_word_note, self.second_word_note, self.distinction)
        ):
            raise ValueError("A contrast response must engage both words and state a distinction")


def _established(word: Word, minimum_stability: float) -> bool:
    state = word.review_state
    # Stability is deliberately required rather than inferred from the
    # strength score.  SM-2/brand-new words have no measured long-horizon
    # stability and must not enter this speculative feature.
    return (
        state.repetitions > 0
        and state.stability is not None
        and state.stability >= minimum_stability
    )


def _pair_key(first: int, second: int) -> frozenset[int]:
    return frozenset((first, second))


def build_contrast_cards(
    words: list[Word],
    graph: KnowledgeGraph,
    *,
    enabled: bool,
    minimum_stability: float = DEFAULT_MIN_STABILITY_DAYS,
    intervention_decisions: tuple[InterventionPairDecision, ...] = (),
    limit: int = MAX_CONTRAST_CARDS,
) -> tuple[ContrastCard, ...]:
    """Build a bounded adjacent sequence without touching review state.

    Decisions with ``contrast`` are preferred.  ``isolate`` decisions reserve
    their pair and suppress even a graph-derived candidate.  If no contrast
    decision exists for a pair, the strongest synonym/antonym edge supplies
    the fallback.
    """
    if not enabled or minimum_stability < 0 or limit <= 0:
        return ()

    by_id = {word.id: word for word in words if word.id is not None}
    eligible = {
        word_id
        for word_id, word in by_id.items()
        if _established(word, minimum_stability)
    }
    if len(eligible) < 2:
        return ()

    decisions_by_pair: dict[frozenset[int], InterventionPairDecision] = {}
    isolated_pairs: set[frozenset[int]] = set()
    for decision in intervention_decisions:
        pair = decision.pair()
        if len(pair) != 2:
            continue
        if decision.strategy == "isolate":
            isolated_pairs.add(pair)
        elif decision.strategy == "contrast" and pair not in decisions_by_pair:
            decisions_by_pair[pair] = decision

    candidates: list[tuple[float, int, int, Relation]] = []
    for pair, decision in decisions_by_pair.items():
        first, second = decision.first_word_id, decision.second_word_id
        if pair in isolated_pairs or not pair <= eligible or first not in by_id or second not in by_id:
            continue
        relations = graph.relations_between(first, second) & CONTRAST_RELATIONS
        # Prefer the stronger synonym edge when both relations are present;
        # this ordering is explicit rather than dependent on enum spelling.
        relation = Relation.SYNONYM if Relation.SYNONYM in relations else Relation.ANTONYM
        candidates.append((2.0, min(first, second), max(first, second), relation))

    for edge in graph.edges:
        if edge.relation not in CONTRAST_RELATIONS:
            continue
        pair = _pair_key(edge.source_id, edge.target_id)
        if pair in isolated_pairs or pair in decisions_by_pair:
            continue
        if pair <= eligible:
            candidates.append((edge.strength, min(edge.source_id, edge.target_id), max(edge.source_id, edge.target_id), edge.relation))

    cards: list[ContrastCard] = []
    seen: set[frozenset[int]] = set()
    for _, first_id, second_id, relation in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        pair = _pair_key(first_id, second_id)
        if pair in seen:
            continue
        first, second = by_id[first_id], by_id[second_id]
        cards.append(
            ContrastCard(
                word_ids=(first_id, second_id),
                terms=(first.term, second.term),
                relation=relation,
                prompt=f"How does {first.term} differ from {second.term}?",
            )
        )
        seen.add(pair)
        if len(cards) >= min(limit, MAX_CONTRAST_CARDS):
            break
    return tuple(cards)


def answer_contrast_card(
    card: ContrastCard,
    *,
    first_word_note: str,
    second_word_note: str,
    distinction: str,
    answered_at: datetime,
) -> ContrastAnswer:
    """Validate a relational answer without invoking an SRS scheduler."""
    return ContrastAnswer(
        card=card,
        first_word_note=first_word_note,
        second_word_note=second_word_note,
        distinction=distinction,
        answered_at=answered_at,
    )
