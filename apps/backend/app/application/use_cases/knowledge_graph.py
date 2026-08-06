"""Keep persisted knowledge-graph edges in sync with mutations (#203 TODO 2).

The whole graph is recomputed in memory on every call — a cheap, pure
Python pass over one account's own vocabulary, not a cross-account
operation and not the "quadratic on read" hazard #180 flags — but only the
edges touching the word that actually changed are written.
`KnowledgeEdgeRepository.replace_for_word` is scoped the same way, so an
edge between two unrelated words is never given a new `updated_at` as a
side effect of a third word's edit.
"""
from __future__ import annotations

from app.domain.repositories import KnowledgeEdgeRepository, WordRepository
from app.domain.services.knowledge_graph import KnowledgeGraph, WordNode, build_edges


def nodes_for(words) -> list[WordNode]:
    """Shared with the read-path callers (graph.py, scenarios.py) so the
    node shape the graph derives edges from is defined exactly once."""
    return [
        WordNode(
            word_id=word.id,
            term=word.term,
            synonyms=tuple(word.synonyms),
            antonyms=tuple(word.antonyms),
            topics=tuple(word.topics),
            collocations=tuple(word.collocations),
            cefr_level=word.cefr_level,
        )
        for word in words
    ]


def confusions_for(mistake_repo, user_id: int) -> dict[tuple[int, int], int]:
    """Word pairs the learner actually mixes up, from the mistake log (#134).

    Shared with the read-path callers for the same reason as `nodes_for`.
    """
    counts: dict[tuple[int, int], int] = {}
    for row in mistake_repo.list_for_user(user_id):
        if row.confused_with_word_id is None or row.confused_with_word_id == row.word_id:
            continue
        key = (min(row.word_id, row.confused_with_word_id), max(row.word_id, row.confused_with_word_id))
        counts[key] = counts.get(key, 0) + row.occurrence_count
    return counts


def graph_for_user(words, edge_repo: KnowledgeEdgeRepository, user_id: int) -> KnowledgeGraph:
    """The one place `graph.py` and `scenarios.py` both built a
    `KnowledgeGraph` from scratch (#203 TODO 5 — previously duplicated
    verbatim in both routers, including the confusion-counting helper).

    Takes pre-loaded `words` rather than a repository, matching the
    original `_graph_for` this replaces: both call sites already load
    their account's words for their own by-id lookups, and fetching them
    a second time here would be a redundant query for the same rows.

    Edges come from the persisted table now, not a fresh `build_edges()`
    call — the only behavior change TODO 4 asks for. `KnowledgeGraph`'s own
    semantics (`.related()`, `.prerequisites()`, ...) are untouched, so a
    caller cannot tell the difference except in speed.
    """
    nodes = nodes_for(words)
    edges = edge_repo.list_all_for_user(user_id)
    return KnowledgeGraph(nodes, edges)


class RecomputeKnowledgeEdgesForWordUseCase:
    """Recomputes and persists only the edges touching one word."""

    def __init__(
        self,
        word_repo: WordRepository,
        edge_repo: KnowledgeEdgeRepository,
        mistake_repo=None,
    ):
        self.word_repo = word_repo
        self.edge_repo = edge_repo
        # Optional so a caller with no mistake log wired (a pure vocabulary
        # edit, for instance) still gets lexical/topic edges recomputed —
        # confusion edges simply stay whatever they already were.
        self.mistake_repo = mistake_repo

    def execute(self, user_id: int, word_id: int) -> None:
        words = self.word_repo.list_all_for_user(user_id)
        if not any(w.id == word_id for w in words):
            # Deleted, or never belonged to this account. Deletion's own
            # edge cleanup is _delete_word_dependents, not this path.
            return

        nodes = nodes_for(words)
        confusions = confusions_for(self.mistake_repo, user_id) if self.mistake_repo is not None else {}
        all_edges = build_edges(nodes, confusions)
        touching = [e for e in all_edges if word_id in (e.source_id, e.target_id)]
        self.edge_repo.replace_for_word(user_id, word_id, touching)
