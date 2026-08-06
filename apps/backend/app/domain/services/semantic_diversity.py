"""Semantic separation when introducing new words (issue #204).

Learning related words in one batch costs trials-to-criterion — d = 0.73
in the meta-analysis embedded in Nakata & Suzuki (2019) — without a
matching retention benefit (d = -0.24, CI crosses zero: this is a rate
effect, not a retention effect, and must not be oversold as either).
This reorders a batch of new-word candidates so semantically related ones
are not introduced back-to-back, and separately deprioritizes any
candidate that overlaps a category the learner has recently studied
(Healy, Schneider & Kole 2025, eta^2 = 0.228 — the harm is not limited to
what is in today's batch).

Pure and deterministic given its inputs — zero framework imports, and it
does not query. Deliberately never applied to the review queue (TODO 5);
see the comment on SqlAlchemyWordRepository.list_due_for_user.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, replace

from app.domain.services.knowledge_graph import KnowledgeEdge, Relation, WordNode, build_edges

# TODO 1: near-synonyms, antonyms and same-topic coordinates are what the
# cited studies manipulated (Nation 2000: near-synonyms, antonyms, same-set
# coordinates, synforms are the riskiest). COLLOCATION is excluded on
# purpose — collocates are thematically, not semantically, related, and
# thematic clustering does not carry the same demonstrated cost.
HIGH_RISK_RELATIONS = (Relation.SYNONYM, Relation.ANTONYM, Relation.TOPIC)


@dataclass(frozen=True)
class DiversityOrdering:
    """`order` holds indices into the original `candidates` list, permuted.

    `deferred_for_recent_study` names the indices pushed to the end because
    they overlap a category the learner has already been studying (TODO 2)
    — kept separate from the batch-internal reordering so a caller can
    explain the two reasons differently (TODO 3).
    """

    order: list[int]
    deferred_for_recent_study: frozenset[int]


def order_for_diversity(
    candidates: list[WordNode],
    recently_studied: list[WordNode] | None = None,
) -> DiversityOrdering:
    """Reorder `candidates` to keep semantically related ones apart.

    `recently_studied` is the learner's own recent vocabulary (TODO 2,
    Healy/Schneider/Kole): a candidate sharing a high-risk relation with
    any of it is deferred to the end of the order, regardless of how it
    relates to the rest of the batch.
    """
    if not candidates:
        return DiversityOrdering(order=[], deferred_for_recent_study=frozenset())

    indexed = [
        WordNode(
            word_id=i,
            term=c.term,
            synonyms=c.synonyms,
            antonyms=c.antonyms,
            topics=c.topics,
            collocations=c.collocations,
            cefr_level=c.cefr_level,
        )
        for i, c in enumerate(candidates)
    ]

    deferred = _overlaps_recent_study(indexed, recently_studied or [])

    batch_edges = _high_risk_edges(indexed)
    eligible = [i for i in range(len(indexed)) if i not in deferred]
    clusters = _clusters(eligible, batch_edges)
    ordered_eligible = _round_robin(clusters)

    return DiversityOrdering(order=[*ordered_eligible, *sorted(deferred)], deferred_for_recent_study=frozenset(deferred))


def _high_risk_edges(nodes: list[WordNode]) -> list[KnowledgeEdge]:
    return [edge for edge in build_edges(nodes) if edge.relation in HIGH_RISK_RELATIONS]


def _overlaps_recent_study(indexed: list[WordNode], recently_studied: list[WordNode]) -> set[int]:
    if not recently_studied:
        return set()
    offset = len(indexed)
    recent_nodes = [replace(node, word_id=offset + i) for i, node in enumerate(recently_studied)]
    combined_edges = _high_risk_edges([*indexed, *recent_nodes])
    recent_ids = {node.word_id for node in recent_nodes}
    deferred: set[int] = set()
    for edge in combined_edges:
        if edge.source_id in recent_ids and edge.target_id < offset:
            deferred.add(edge.target_id)
        elif edge.target_id in recent_ids and edge.source_id < offset:
            deferred.add(edge.source_id)
    return deferred


def _clusters(indices: list[int], edges: list[KnowledgeEdge]) -> list[list[int]]:
    """Union-find over `indices`, connected by `edges` — a semantic "set"
    (colours, animals, ...) becomes one cluster to spread apart, the same
    shape the cited studies' stimulus sets take."""
    parent = {i: i for i in indices}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    present = set(indices)
    for edge in edges:
        if edge.source_id in present and edge.target_id in present:
            union(edge.source_id, edge.target_id)

    grouped: dict[int, list[int]] = {}
    for i in indices:
        grouped.setdefault(find(i), []).append(i)
    for members in grouped.values():
        members.sort()
    # Largest clusters first: those are the ones most in need of spreading,
    # and interleaving them first gives every later, smaller cluster room.
    return sorted(grouped.values(), key=lambda members: (-len(members), members[0]))


def _round_robin(clusters: list[list[int]]) -> list[int]:
    """Greedily take the next item from whichever cluster currently has the
    most left, skipping the cluster just used — the standard "reorganize
    string" / task-scheduler algorithm, with a one-slot cooldown, which is
    what "not adjacent" requires. A naive one-item-per-cluster-per-round
    pass fails once smaller clusters run out and the largest cluster still
    has items left to place: it then dumps its remainder back-to-back
    exactly where separation matters most.
    """
    heap = [(-len(members), cluster_index, list(members)) for cluster_index, members in enumerate(clusters)]
    heapq.heapify(heap)

    order: list[int] = []
    on_cooldown: tuple[int, int, list[int]] | None = None
    while heap:
        count, cluster_index, members = heapq.heappop(heap)
        order.append(members.pop(0))
        if on_cooldown is not None:
            heapq.heappush(heap, on_cooldown)
        on_cooldown = (count + 1, cluster_index, members) if members else None
    if on_cooldown is not None:
        # Only one cluster had anything left when the heap ran dry — nothing
        # remains to interleave it against, so its remainder (already
        # ascending) is appended as-is rather than silently dropped.
        order.extend(on_cooldown[2])
    return order
