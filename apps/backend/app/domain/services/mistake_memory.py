"""Which mistakes are still worth reviewing (issue #142, from #78).

A record of every error a learner ever made is a growing list of accusations.
The thing that makes it useful rather than demoralising is that mistakes
*expire*: getting a word right repeatedly should retire the mistake, and a
mistake from a year ago that has not recurred is not a mistake you still have.

**Resolution is derived, never stored.** Nothing here writes a `resolved` flag
back onto a mistake row. Mistake events are append-only history (#134), and a
flag would be a second, mutable copy of a fact already implied by the review
log — one that can disagree with it. Deriving it means the answer is always
consistent with what actually happened, and that re-deriving after a bug fix
corrects the past instead of leaving stale flags behind.

**Decay is by successful reviews, not by clock.** Time passing is not evidence
of learning; a word untouched for six months has not been relearned, it has
been avoided. Only getting it right counts, which is why the input here is the
review log rather than a duration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Correct answers after a mistake before it is considered resolved. Three
# rather than one, because a single correct answer immediately after getting it
# wrong is often the learner repeating what they were just shown rather than
# recalling it.
SUCCESSES_TO_RESOLVE = 3

# What each success is worth against a mistake's strength. A mistake made three
# times does not vanish on the first correct answer, and one made once should
# not linger after three.
DECAY_PER_SUCCESS = 1.0 / SUCCESSES_TO_RESOLVE


@dataclass(frozen=True)
class RecordedMistake:
    """One mistake, as history holds it."""

    word_id: int
    occurred_at: datetime
    category: str
    occurrences: int = 1


@dataclass(frozen=True)
class MistakeMemory:
    """A word's outstanding mistakes, after successful reviews are counted."""

    word_id: int
    mistake_count: int
    # Correct answers recorded *after* the most recent mistake. Earlier
    # successes are not counted: getting a word right and then wrong again
    # means the earlier success did not stick, and crediting it would retire a
    # mistake the learner demonstrably still has.
    successes_since: int
    # 1.0 for an untouched mistake, falling to 0.0 as it is answered correctly.
    # Carried rather than recomputed by callers so ordering and resolution
    # cannot drift apart.
    strength: float
    last_mistake_at: datetime
    categories: tuple[str, ...]

    @property
    def resolved(self) -> bool:
        return self.strength <= 0.0


def build_memories(
    mistakes: list[RecordedMistake], correct_answers: dict[int, list[datetime]]
) -> list[MistakeMemory]:
    """Fold a mistake log and a review log into per-word memories.

    `correct_answers` maps a word id to the times it was answered correctly.
    Passed in whole rather than pre-filtered because "since the last mistake"
    is decided here — a caller that filtered first would have to know this
    rule, and two places knowing it is one too many.
    """
    by_word: dict[int, list[RecordedMistake]] = {}
    for mistake in mistakes:
        by_word.setdefault(mistake.word_id, []).append(mistake)

    memories = []
    for word_id, word_mistakes in by_word.items():
        last_at = max(m.occurred_at for m in word_mistakes)
        successes = sum(1 for at in correct_answers.get(word_id, []) if at > last_at)
        total = sum(m.occurrences for m in word_mistakes)

        # Clamped at both ends: a word answered correctly ten times is resolved,
        # not negatively wrong, and one never answered since is at full strength.
        strength = max(0.0, 1.0 - successes * DECAY_PER_SUCCESS)

        memories.append(
            MistakeMemory(
                word_id=word_id,
                mistake_count=total,
                successes_since=successes,
                strength=round(strength, 4),
                last_mistake_at=last_at,
                categories=tuple(sorted({m.category for m in word_mistakes})),
            )
        )

    return sorted(memories, key=_review_order)


def unresolved(memories: list[MistakeMemory]) -> list[MistakeMemory]:
    return [m for m in memories if not m.resolved]


def _review_order(memory: MistakeMemory) -> tuple:
    """Worst first, then most recent.

    Strength leads because a word still fully wrong matters more than one
    nearly retired. Repetition breaks ties before recency: a word missed five
    times last week is a bigger problem than one missed once yesterday, and
    ordering by recency alone would keep showing whatever was reviewed last.
    """
    return (-memory.strength, -memory.mistake_count, -memory.last_mistake_at.timestamp(), memory.word_id)


def select_for_session(memories: list[MistakeMemory], limit: int) -> list[int]:
    """Word ids for a "review my mistakes" session, worst first.

    Resolved mistakes are excluded rather than ranked last. A session that
    quietly pads itself with words the learner has already fixed is a session
    that misrepresents what it is — and the honest short session is the one
    that tells them there is little left to review.
    """
    if limit <= 0:
        return []
    return [memory.word_id for memory in unresolved(memories)][:limit]
