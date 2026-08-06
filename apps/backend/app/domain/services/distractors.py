"""Semantically related multiple-choice distractors (issue #205).

Little & Bjork (2015) found a *competitive* distractor — one that competes
with the correct answer for the same retrieval cue — strengthens later
recall of the distractor itself (47% vs 36% for a noncompetitive one, at
identical exposure). A noncompetitive distractor, which is what a uniform
random pick usually is, gives no benefit at all. This module picks
competitive distractors from the account's own knowledge graph instead.

Pure and deterministic given its inputs (including the RNG). It does not
query and does not touch FSRS scheduling — see TODO 2 of #205 for the
isolation hazard this deliberately does not address here, because it
requires a scheduler-correctness decision this module has no business
making unilaterally.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.domain.entities import Word
from app.domain.services.knowledge_graph import KnowledgeGraph, Relation
from app.domain.value_objects import ReviewState

# TODO 7: bound the false-fact risk from MC lures (Roediger & Marsh 2005) —
# keep the option count low regardless of what a caller asks for.
MAX_DISTRACTORS = 3

# Relations that make a word a competitive distractor for another. Not
# CONFUSED_WITH: that edge is derived from mistakes already made against
# *this* target, so offering it back as an answer choice would hand the
# learner their own most-confused word rather than exercising discrimination
# against it.
COMPETITIVE_RELATIONS = (Relation.SYNONYM, Relation.ANTONYM, Relation.TOPIC)

# TODO 3: how established a word must be (FSRS stability, in days) before a
# competitive distractor is used against it. Nation (2000) is explicit that
# the correct value is unknown ("There is no research to tell us how well
# established an item needs to be before it can be safely contrasted") — this
# is a conservative starting point, provisional pending measurement, not a
# settled threshold.
DEFAULT_MIN_STABILITY_FOR_COMPETITIVE_DISTRACTORS = 21.0

# TODO 4: Baxter et al. (2021) found the contrast benefit limited to skilled
# readers; weaker readers paid the learning-phase accuracy cost with no later
# benefit. There is no persisted per-learner CEFR level in this codebase, so
# average "Learning Strength" (0-100) across the account's own words is used
# as the available proxy for "measured accuracy" the issue names as the
# alternative — a below-threshold account never sees competitive distractors.
DEFAULT_MIN_ACCOUNT_STRENGTH_FOR_COMPETITIVE_DISTRACTORS = 60.0


@dataclass(frozen=True)
class DistractorSelection:
    """`options` includes the correct answer, shuffled in. `competitive` is
    the subset that came from the graph rather than a random pick — the
    signal TODO 2's (not yet implemented) FSRS isolation would key off of.
    """

    options: list[str]
    competitive: frozenset[str]


def select_distractors(
    target: Word,
    correct_answer: str,
    candidate_words: list[Word],
    graph: KnowledgeGraph,
    review_state: ReviewState,
    account_average_strength: float,
    count: int = 2,
    min_stability: float = DEFAULT_MIN_STABILITY_FOR_COMPETITIVE_DISTRACTORS,
    min_account_strength: float = DEFAULT_MIN_ACCOUNT_STRENGTH_FOR_COMPETITIVE_DISTRACTORS,
    rng: random.Random | None = None,
) -> DistractorSelection:
    """Pick up to `count` (capped at `MAX_DISTRACTORS`) wrong answers for a
    multiple-choice question on `target`.

    Prefers competitive (graph-related) distractors when both gates pass —
    the word itself is established enough (TODO 3) and the account as a
    whole is accurate enough overall (TODO 4) — and always falls back to
    filling any remaining slots from the wider candidate pool, which is
    what actually fixes the "None of the above" defect (TODO 5): the pool
    is the caller's full vocabulary, not whatever happened to already be
    loaded into one session's queue.
    """
    rng = rng or random.Random()
    count = min(count, MAX_DISTRACTORS)

    others = [w for w in candidate_words if w.id != target.id and w.translations]
    eligible_for_competitive = (
        review_state.stability is not None
        and review_state.stability >= min_stability
        and account_average_strength >= min_account_strength
    )

    competitive_terms: list[str] = []
    used_word_ids: set[int] = set()
    if eligible_for_competitive and target.id is not None:
        by_id = {w.id: w for w in others if w.id is not None}
        for edge in graph.related(target.id, limit=len(graph.edges) or 1):
            if edge.relation not in COMPETITIVE_RELATIONS:
                continue
            other_id = edge.target_id if edge.source_id == target.id else edge.source_id
            other = by_id.get(other_id)
            if other is None or other_id in used_word_ids:
                continue
            answer = other.translations[0]
            if answer.strip().casefold() == correct_answer.strip().casefold():
                continue
            competitive_terms.append(answer)
            used_word_ids.add(other_id)
            if len(competitive_terms) >= count:
                break

    filler_pool = [
        w.translations[0]
        for w in others
        if w.id not in used_word_ids
        and w.translations[0].strip().casefold() != correct_answer.strip().casefold()
    ]
    rng.shuffle(filler_pool)

    distractors = list(competitive_terms)
    seen = {d.strip().casefold() for d in distractors}
    for candidate in filler_pool:
        if len(distractors) >= count:
            break
        key = candidate.strip().casefold()
        if key in seen:
            continue
        distractors.append(candidate)
        seen.add(key)

    options = [correct_answer, *distractors]
    rng.shuffle(options)
    return DistractorSelection(options=options, competitive=frozenset(competitive_terms))
