"""Relations between the words one learner is studying (issue #138, from #77).

Words already carry synonyms, antonyms, topics and collocations as free text.
That is enough to render a mind map and not enough to answer a question. The
difference this makes is turning "gato has a synonym string 'minino'" into
"these two *cards you own* are related", which is what lets the graph answer
what to learn first, what keeps being confused, and what belongs together.

Two rules shape the whole thing.

**Edges only ever join words the learner has.** A synonym string that matches
nothing in their deck is vocabulary they do not study, and an edge to it would
be an edge to nothing — a graph full of dangling references that looks rich
and answers nothing.

**Strength is evidence, not opinion.** Every edge carries what produced it, so
"related because you wrote them as synonyms" and "related because you confuse
them" stay distinguishable. A single number would collapse a fact the learner
asserted with a pattern we inferred, and those deserve different trust.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Relation(str, Enum):
    """How two words relate.

    Closed, because each member needs a rule for deriving it and a meaning in
    the queries below. A free-form relation string would describe the data
    rather than answer anything.
    """

    SYNONYM = "synonym"
    ANTONYM = "antonym"
    # Share a topic. Weaker than the others by nature — two words about
    # "travel" are related the way any two words in a category are.
    TOPIC = "topic"
    # Appear together in usage. Directional in language but stored
    # symmetrically; which word "collocates with" which is not a distinction
    # the queries here need.
    COLLOCATION = "collocation"
    # Derived from mistakes rather than asserted by the learner (#134).
    CONFUSED_WITH = "confused_with"


# How much each relation is worth when ranking. Confusion outranks everything
# because it is observed behaviour rather than a label someone typed, and a
# word you keep mixing up is more urgent than one you filed under the same
# topic.
RELATION_WEIGHT: dict[Relation, float] = {
    Relation.CONFUSED_WITH: 1.0,
    Relation.SYNONYM: 0.8,
    Relation.ANTONYM: 0.7,
    Relation.COLLOCATION: 0.5,
    Relation.TOPIC: 0.3,
}


@dataclass(frozen=True)
class KnowledgeEdge:
    """One relation between two of the learner's own words.

    Stored with the lower id first so a relation is one edge however it was
    discovered — deriving it from both endpoints must not produce two.
    """

    source_id: int
    target_id: int
    relation: Relation
    # What produced this edge, in words. Kept so the graph can say *why* two
    # things are related rather than only that they are — a graph that cannot
    # justify an edge is one nobody trusts enough to act on.
    evidence: str
    occurrences: int = 1

    @property
    def strength(self) -> float:
        """Ranking weight. Repetition raises it, with diminishing returns.

        Capped at twice the base: a word pair confused ten times is not ten
        times more urgent than one confused twice, and letting repetition
        dominate would bury a strong-but-single relation under a weak-but-
        frequent one.
        """
        base = RELATION_WEIGHT[self.relation]
        return round(min(base * (1 + 0.2 * (self.occurrences - 1)), base * 2), 4)


@dataclass(frozen=True)
class WordNode:
    """A word as the graph sees it. Only the fields relations derive from."""

    word_id: int
    term: str
    synonyms: tuple[str, ...] = ()
    antonyms: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    collocations: tuple[str, ...] = ()
    # Used to answer "what should I learn before this". None means unknown,
    # which is different from A1 and must not sort as if it were.
    cefr_level: str | None = None


_CEFR_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def build_edges(
    nodes: list[WordNode],
    confusions: dict[tuple[int, int], int] | None = None,
    notes: list["TopicNote"] | None = None,
) -> list[KnowledgeEdge]:
    """Derive every edge from the learner's own vocabulary.

    `confusions` maps an ordered word-id pair to how often they were mixed up,
    which is what #134 produces. Absent, the graph is built from the lexical
    fields alone and is simply less informative — not broken.

    `notes` is optional and additive (#203 TODO 3): pass a list to have the
    topic pass append what it bounded or skipped and why. Every existing
    caller that omits it is unaffected.
    """
    by_term = {node.term.strip().casefold(): node.word_id for node in nodes}
    seen: dict[tuple[int, int, Relation], KnowledgeEdge] = {}

    lexical = (
        ("synonyms", Relation.SYNONYM),
        ("antonyms", Relation.ANTONYM),
        ("collocations", Relation.COLLOCATION),
    )
    for node in nodes:
        for field_name, relation in lexical:
            for other in getattr(node, field_name):
                target = by_term.get(other.strip().casefold())
                # Skipped when the term is not a word the learner has, and when
                # it resolves to the word itself — a word listed as its own
                # synonym is a data-entry slip, not a relation.
                if target is None or target == node.word_id:
                    continue
                _add(seen, node.word_id, target, relation, f"listed as a {relation.value}")

    _add_topic_edges(nodes, seen, notes)

    for (first, second), count in (confusions or {}).items():
        if first == second:
            continue
        _add(
            seen,
            first,
            second,
            Relation.CONFUSED_WITH,
            f"answered one for the other {count} time(s)",
            occurrences=count,
        )

    return sorted(seen.values(), key=lambda e: (-e.strength, e.source_id, e.target_id))


class TopicSuppressionReason(str, Enum):
    """Why a topic's edges look the way they do — #203 TODO 3.

    Recorded rather than left to be inferred from an edge count that could
    just as easily mean "nobody shares this topic" as "we bounded it."
    """

    TOO_FEW_MEMBERS = "too_few_members"
    # The cap was hit. Edges are still produced — a deterministic subset,
    # never zero — which is the behavior this reason exists to distinguish
    # from the old silent-drop.
    BOUNDED = "bounded"


@dataclass(frozen=True)
class TopicNote:
    topic: str
    member_count: int
    reason: TopicSuppressionReason
    edges_included: int


# Quadratic in the size of a topic, which is why membership is capped: a
# learner who tags four hundred words "general" would otherwise generate
# eighty thousand edges that say nothing. Capping at 50 (1,225 possible
# pairs) keeps the pass bounded without special-casing it away entirely.
_TOPIC_MEMBER_CAP = 50


def _add_topic_edges(nodes: list[WordNode], seen: dict, notes: list[TopicNote] | None = None) -> None:
    """Join words sharing a topic.

    A topic over the cap is bounded to a deterministic subset — sorted by
    word id, not insertion order, so the same deck always bounds to the
    same edges regardless of what order its words happen to load in —
    rather than dropped to zero edges. Nothing is silently discarded: a
    topic that produced no edges did not have enough members to relate,
    which `notes` (when supplied) records explicitly.
    """
    by_topic: dict[str, list[WordNode]] = {}
    for node in nodes:
        for topic in node.topics:
            by_topic.setdefault(topic.strip().casefold(), []).append(node)

    for topic, members in by_topic.items():
        if len(members) < 2:
            if notes is not None:
                notes.append(TopicNote(topic, len(members), TopicSuppressionReason.TOO_FEW_MEMBERS, 0))
            continue

        over_cap = len(members) > _TOPIC_MEMBER_CAP
        included = sorted(members, key=lambda n: n.word_id)[:_TOPIC_MEMBER_CAP] if over_cap else members
        if over_cap and notes is not None:
            pair_count = len(included) * (len(included) - 1) // 2
            notes.append(TopicNote(topic, len(members), TopicSuppressionReason.BOUNDED, pair_count))

        for index, first in enumerate(included):
            for second in included[index + 1 :]:
                _add(seen, first.word_id, second.word_id, Relation.TOPIC, f"both tagged '{topic}'")


def _add(
    seen: dict,
    a: int,
    b: int,
    relation: Relation,
    evidence: str,
    occurrences: int = 1,
) -> None:
    key = (min(a, b), max(a, b), relation)
    existing = seen.get(key)
    if existing is not None:
        # Discovered from both ends. Counted once, but the count reflects that
        # both words assert it — mutual agreement is mild extra evidence.
        seen[key] = KnowledgeEdge(
            source_id=key[0],
            target_id=key[1],
            relation=relation,
            evidence=existing.evidence,
            occurrences=max(existing.occurrences, occurrences),
        )
        return
    seen[key] = KnowledgeEdge(
        source_id=key[0], target_id=key[1], relation=relation, evidence=evidence, occurrences=occurrences
    )


class KnowledgeGraph:
    """Queries over derived edges. Pure: it holds no session and no repository."""

    def __init__(self, nodes: list[WordNode], edges: list[KnowledgeEdge]):
        self.nodes = {node.word_id: node for node in nodes}
        self.edges = edges

    def __eq__(self, other: object) -> bool:
        # Value equality rather than the default identity comparison —
        # needed so a fixture embedding a graph (#183's golden dataset) can
        # itself be compared for reproducibility. Nothing in a live request
        # path compares two KnowledgeGraph instances, so this has no
        # bearing on #203's byte-identical-endpoints guarantee.
        if not isinstance(other, KnowledgeGraph):
            return NotImplemented
        return self.nodes == other.nodes and self.edges == other.edges

    def related(self, word_id: int, limit: int = 10) -> list[KnowledgeEdge]:
        """Everything joined to this word, strongest first."""
        touching = [e for e in self.edges if word_id in (e.source_id, e.target_id)]
        return sorted(touching, key=lambda e: (-e.strength, e.source_id, e.target_id))[:limit]

    def confused_with(self, word_id: int) -> list[KnowledgeEdge]:
        return [e for e in self.related(word_id, limit=len(self.edges) or 1)
                if e.relation is Relation.CONFUSED_WITH]

    def topic_words(self, topic: str) -> list[int]:
        wanted = topic.strip().casefold()
        return sorted(
            node.word_id
            for node in self.nodes.values()
            if any(t.strip().casefold() == wanted for t in node.topics)
        )

    def prerequisites(self, word_id: int) -> list[int]:
        """Related words that are strictly easier, easiest first.

        "What should I learn before this?" A related word at the *same* level
        is not a prerequisite, and one with no level recorded is unknown rather
        than easy — including it would answer the question with a guess.
        """
        target = self.nodes.get(word_id)
        if target is None or target.cefr_level not in _CEFR_ORDER:
            return []
        ceiling = _CEFR_ORDER[target.cefr_level]

        # Keyed by word, not by edge. Two words can be related more than one
        # way — sharing a topic *and* being confused with each other — and a
        # prerequisite list that named the same word twice would be a bug the
        # caller has to work around.
        easier: dict[int, int] = {}
        for edge in self.related(word_id, limit=len(self.edges) or 1):
            other_id = edge.target_id if edge.source_id == word_id else edge.source_id
            other = self.nodes.get(other_id)
            if other is None or other.cefr_level not in _CEFR_ORDER:
                continue
            if _CEFR_ORDER[other.cefr_level] < ceiling:
                easier[other_id] = _CEFR_ORDER[other.cefr_level]
        return [wid for wid, _ in sorted(easier.items(), key=lambda item: (item[1], item[0]))]
