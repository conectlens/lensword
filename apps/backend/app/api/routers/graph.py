"""Knowledge-graph search and CEFR progress (issue #143).

Both routes are whole-vocabulary questions, so both build from every word the
learner owns rather than one group. A graph scoped to a group would report that
words filed separately are unrelated, which is a statement about their filing
rather than their language.
"""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, MistakeEventRepo, WordRepo
from app.api.schemas.graph import (
    CefrProgressResponse,
    LevelProgressResponse,
    PrerequisitesResponse,
    RelatedWordResponse,
)
from app.domain.services.cefr_progress import CEFR_LEVELS, ScoredWord, build_progress
from app.domain.services.knowledge_graph import (
    KnowledgeGraph,
    WordNode,
    build_edges,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge graph"])


@router.get("/words/{word_id}/prerequisites", response_model=PrerequisitesResponse)
def word_prerequisites(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, mistake_repo: MistakeEventRepo
):
    """"What should I learn before this word?"

    Answered from related words the learner already has that sit at a strictly
    easier CEFR level. A word at the *same* level is not a prerequisite, and one
    with no level recorded is unknown rather than easy — including it would
    answer the question with a guess.
    """
    words = word_repo.list_all_for_user(current_user.id)
    target = next((w for w in words if w.id == word_id), None)
    if target is None:
        # 404 whether the word is missing or belongs to someone else. A
        # distinguishable 403 would confirm the existence of another account's
        # word to anyone who cared to enumerate ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")

    graph = _graph_for(words, _confusions_for(mistake_repo, current_user.id))
    by_id = {w.id: w for w in words}

    prerequisites = []
    for prerequisite_id in graph.prerequisites(word_id):
        word = by_id.get(prerequisite_id)
        if word is None:
            continue
        edge = next(
            (
                e
                for e in graph.related(word_id, limit=len(graph.edges) or 1)
                if prerequisite_id in (e.source_id, e.target_id)
            ),
            None,
        )
        prerequisites.append(
            RelatedWordResponse(
                word_id=word.id,
                term=word.term,
                relation=edge.relation.value if edge else "topic",
                strength=edge.strength if edge else 0.0,
                evidence=edge.evidence if edge else "",
            )
        )

    return PrerequisitesResponse(
        word_id=target.id,
        term=target.term,
        cefr_level=target.cefr_level,
        prerequisites=prerequisites,
        level_unknown=not _has_known_level(target.cefr_level),
    )


@router.get("/words/{word_id}/related", response_model=list[RelatedWordResponse])
def related_words(
    word_id: int,
    current_user: CurrentUser,
    word_repo: WordRepo,
    mistake_repo: MistakeEventRepo,
    limit: int = 10,
):
    """Everything joined to this word, strongest first."""
    words = word_repo.list_all_for_user(current_user.id)
    if not any(w.id == word_id for w in words):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")

    graph = _graph_for(words, _confusions_for(mistake_repo, current_user.id))
    by_id = {w.id: w for w in words}

    out = []
    for edge in graph.related(word_id, limit=limit):
        other_id = edge.target_id if edge.source_id == word_id else edge.source_id
        other = by_id.get(other_id)
        if other is None:
            continue
        out.append(
            RelatedWordResponse(
                word_id=other.id,
                term=other.term,
                relation=edge.relation.value,
                strength=edge.strength,
                evidence=edge.evidence,
            )
        )
    return out


@router.get("/me/cefr-progress", response_model=CefrProgressResponse)
def cefr_progress(current_user: CurrentUser, word_repo: WordRepo) -> CefrProgressResponse:
    """Per-level progress. Deliberately does not name an overall level.

    A CEFR level describes what a person can *do* in a language; what we hold
    is which words are in their deck and how well they recall them. Someone who
    added forty C1 words yesterday is not C1, and publishing a single level
    would be a confident claim built from a proxy.
    """
    words = word_repo.list_all_for_user(current_user.id)
    progress = build_progress(
        [
            ScoredWord(
                cefr_level=word.cefr_level,
                strength=word.review_state.strength,
                repetitions=word.review_state.repetitions,
            )
            for word in words
        ]
    )

    return CefrProgressResponse(
        levels=[_level_response(level) for level in progress.levels],
        unlevelled=_level_response(progress.unlevelled) if progress.unlevelled else None,
        total_words=progress.total_words,
    )


def _confusions_for(mistake_repo, user_id: int) -> dict[tuple[int, int], int]:
    """Word pairs the learner actually mixes up, from the mistake log (#134).

    This is what makes CONFUSED_WITH more than a placeholder: it is the one
    relation derived from observed behaviour rather than a label someone typed,
    which is why it outranks every other kind of edge.
    """
    counts: dict[tuple[int, int], int] = {}
    for row in mistake_repo.list_for_user(user_id):
        if row.confused_with_word_id is None or row.confused_with_word_id == row.word_id:
            continue
        key = (min(row.word_id, row.confused_with_word_id), max(row.word_id, row.confused_with_word_id))
        counts[key] = counts.get(key, 0) + row.occurrence_count
    return counts


def _graph_for(words, confusions=None) -> KnowledgeGraph:
    nodes = [
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
    return KnowledgeGraph(nodes, build_edges(nodes, confusions))


def _has_known_level(level: str | None) -> bool:
    return (level or "").strip().upper() in CEFR_LEVELS


def _level_response(level) -> LevelProgressResponse:
    return LevelProgressResponse(
        level=level.level,
        total=level.total,
        started=level.started,
        mastered=level.mastered,
        mastery_share=level.mastery_share,
    )
