"""Progress across CEFR levels (issue #143, from #78).

Words already carry `cefr_level`, so the axis has data. What this adds is the
per-level breakdown — and two refusals that matter more than the arithmetic.

**No single "your level is B2".** It is the number everyone wants and the one
this data cannot support: a CEFR level describes what a person can *do* in a
language, and what we hold is which words are in their deck and how well they
recall them. Someone who added forty C1 words yesterday is not C1. Naming a
level would be a confident claim built from a proxy, and learners would take it
to mean something it does not.

**Words with no level are counted separately, never folded in.** Most decks are
full of them — anything typed by hand rather than enriched. Distributing them
across levels would invent data, and dropping them would make the totals
disagree with the learner's own word count, which is the fastest way to make a
progress screen untrustworthy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ordered, because a progress view has to render A1 before C2 regardless of
# what order the words came back in.
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

# Strength at which a word counts as mastered. Matches WordStatus.MASTERED.
MASTERY_STRENGTH = 80


@dataclass(frozen=True)
class ScoredWord:
    """A word as this view needs it."""

    cefr_level: str | None
    strength: float
    repetitions: int

    @property
    def started(self) -> bool:
        return self.repetitions > 0

    @property
    def mastered(self) -> bool:
        # Deliberately measured by strength rather than by WordStatus, which
        # reports NEEDS_REVIEW for anything past its due date — including words
        # that are thoroughly mastered and merely due. Progress that dropped
        # every time a review came round would be measuring the schedule, not
        # the learner.
        return self.repetitions > 0 and self.strength >= MASTERY_STRENGTH


@dataclass(frozen=True)
class LevelProgress:
    level: str
    total: int
    started: int
    mastered: int

    @property
    def mastery_share(self) -> float:
        """Mastered as a fraction of words held at this level.

        Of what the learner *has*, not of the level itself — we do not know how
        many B2 words exist, and pretending to would turn a real fraction into
        an invented one.
        """
        return round(self.mastered / self.total, 4) if self.total else 0.0


@dataclass
class CefrProgress:
    levels: list[LevelProgress] = field(default_factory=list)
    # Words with no CEFR level recorded. Reported on its own so the parts still
    # add up to the learner's actual word count.
    unlevelled: LevelProgress | None = None
    total_words: int = 0

    @property
    def levelled_words(self) -> int:
        return sum(level.total for level in self.levels)


def build_progress(words: list[ScoredWord]) -> CefrProgress:
    """Per-level counts, every level present.

    Levels with no words are included rather than omitted: a gap in the axis
    reads as "no data was collected", while a zero reads as "you have nothing
    here yet" — and the second is the true one.
    """
    buckets: dict[str, list[ScoredWord]] = {level: [] for level in CEFR_LEVELS}
    unknown: list[ScoredWord] = []

    for word in words:
        level = (word.cefr_level or "").strip().upper()
        if level in buckets:
            buckets[level].append(word)
        else:
            # Includes both "no level recorded" and anything unrecognised. A
            # value this build has no meaning for is data, not a crash.
            unknown.append(word)

    return CefrProgress(
        levels=[_summarise(level, buckets[level]) for level in CEFR_LEVELS],
        unlevelled=_summarise("unknown", unknown) if unknown else None,
        total_words=len(words),
    )


def _summarise(level: str, words: list[ScoredWord]) -> LevelProgress:
    return LevelProgress(
        level=level,
        total=len(words),
        started=sum(1 for word in words if word.started),
        mastered=sum(1 for word in words if word.mastered),
    )
