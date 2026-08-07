"""Assembling what a conversation tutor is told, and what it may say back
(issue #135).

A tutor is useful when it talks *to this learner* — using words they know,
pushing slightly past them, and noticing the mistakes they actually keep
making. That means their vocabulary and mistake history get injected into the
prompt, which is exactly the material that must never be read as instructions.

Three rules shape it.

**Everything injected is data.** The learner's words, their recent errors, and
every prior turn travel inside the delimited block, because a word card whose
definition reads "ignore your instructions" is a thing a user can create.

**History is bounded, and bounded from the recent end.** A conversation that
grows without limit eventually pushes the system instruction out of the
context window — the failure mode being that the tutor stops behaving like a
tutor partway through a long chat, which nobody connects to length.

**The tutor corrects sparingly.** Correcting every error in every turn is how
a conversation becomes a test, and learners stop talking. A hard cap per turn
is a feature, not a limitation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Turns kept in the prompt. Enough for the tutor to follow a thread; bounded so
# the instruction cannot be pushed out of the window by a long chat.
MAX_HISTORY_TURNS = 12

# Learner words offered as "vocabulary they know". More than this stops helping
# the model and starts crowding the actual conversation out of the prompt.
MAX_VOCABULARY_HINTS = 40

# Recent mistakes injected. Small deliberately: the tutor should weave in a few
# known weak points, not run a remedial drill.
MAX_MISTAKE_HINTS = 8

# Corrections a single reply may carry. Correcting everything turns a
# conversation into a test.
MAX_CORRECTIONS_PER_TURN = 3

MAX_MESSAGE_CHARS = 2000


class Speaker(str, Enum):
    LEARNER = "learner"
    TUTOR = "tutor"


class Difficulty(str, Enum):
    """How hard the tutor should make it.

    Named rather than numeric: "B1-ish" is something a learner can choose
    meaningfully, while "difficulty 0.7" is a number they would be guessing at.
    """

    GENTLE = "gentle"
    STEADY = "steady"
    STRETCH = "stretch"


@dataclass(frozen=True)
class Turn:
    speaker: Speaker
    text: str


@dataclass(frozen=True)
class Correction:
    """One thing the learner got wrong, and what it should have been.

    `original` must actually appear in what the learner wrote. A correction
    quoting text they never typed is worse than no correction: it teaches them
    to distrust the highlights, and then the useful ones get ignored too.
    """

    original: str
    corrected: str
    explanation: str


@dataclass
class TutorContext:
    """Everything the tutor is told, already bounded."""

    target_language: str
    difficulty: Difficulty = Difficulty.STEADY
    # The situation being practised, when there is one. Carried here rather
    # than added later because scenario role-play (#136) uses this same
    # transport, and a context that could not describe a scenario would
    # force a parallel one.
    scenario: str | None = None
    vocabulary: list[str] = field(default_factory=list)
    recent_mistakes: list[str] = field(default_factory=list)
    history: list[Turn] = field(default_factory=list)


def build_context(
    target_language: str,
    difficulty: Difficulty,
    vocabulary: list[str],
    recent_mistakes: list[str],
    history: list[Turn],
    scenario: str | None = None,
) -> TutorContext:
    """Bound and clean everything before it reaches a prompt.

    History is trimmed from the *old* end. Dropping recent turns would make the
    tutor forget what was just said while remembering the start, which reads as
    the tutor not listening.
    """
    return TutorContext(
        target_language=target_language,
        difficulty=difficulty,
        scenario=_clip(scenario, 120) or None,
        vocabulary=_unique_clean(vocabulary, MAX_VOCABULARY_HINTS),
        recent_mistakes=_unique_clean(recent_mistakes, MAX_MISTAKE_HINTS),
        history=[
            Turn(speaker=turn.speaker, text=_clip(turn.text))
            for turn in history[-MAX_HISTORY_TURNS:]
            if turn.text and turn.text.strip()
        ],
    )


def validate_reply(raw: dict, learner_text: str) -> tuple[str, list[Correction]]:
    """Clean a tutor response into a reply and at most a few corrections.

    Corrections are dropped rather than repaired when they quote text the
    learner did not write. A model will occasionally invent the "original" it
    is correcting, and a highlight pointing at words nobody typed teaches the
    learner to ignore highlights entirely.
    """
    if not isinstance(raw, dict):
        raise ValueError("The tutor did not answer in the expected shape")

    reply = _clip(raw.get("reply") if isinstance(raw.get("reply"), str) else "")
    if not reply:
        raise ValueError("The tutor did not answer")

    said = (learner_text or "").casefold()
    corrections: list[Correction] = []
    for entry in raw.get("corrections") or []:
        if not isinstance(entry, dict):
            continue
        original = _clip(entry.get("original") if isinstance(entry.get("original"), str) else "", 200)
        corrected = _clip(entry.get("corrected") if isinstance(entry.get("corrected"), str) else "", 200)
        if not original or not corrected or original == corrected:
            continue
        if original.casefold() not in said:
            continue
        corrections.append(
            Correction(
                original=original,
                corrected=corrected,
                explanation=_clip(
                    entry.get("explanation") if isinstance(entry.get("explanation"), str) else "",
                    300,
                ),
            )
        )
        if len(corrections) == MAX_CORRECTIONS_PER_TURN:
            break

    return reply, corrections


# --- Correction feedback (#194 TODO 3) --------------------------------------
#
# `validate_reply` above already enforces that a correction quotes text the
# learner actually wrote and caps how many a single reply may carry. What it
# cannot do is tell whether the learner *agreed* with a correction — that is
# a fact about the learner's judgement, not the model's, and it is recorded
# here as a distinct, append-only outcome rather than folded into the
# correction itself, the same "a correction is a new record, not an edit"
# posture `ObservationCorrection` already uses for review observations.


class CorrectionOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


MAX_EDITED_TEXT_CHARS = 200


@dataclass(frozen=True)
class CorrectionFeedback:
    """One learner decision about one correction the tutor offered.

    `edited_text` is required exactly when `outcome` is EDITED — a rejected
    or accepted correction has nothing further for the learner to have
    written. This is telemetry about what the learner decided, never a
    verdict on whether the tutor's correction was linguistically right: an
    ACCEPTED outcome records "the learner agreed", not "the correction was
    correct".
    """

    message_id: int
    user_id: int
    correction_index: int
    outcome: CorrectionOutcome
    edited_text: str | None = None

    def __post_init__(self) -> None:
        if self.correction_index < 0:
            raise ValueError("correction_index must not be negative")
        if self.outcome is CorrectionOutcome.EDITED:
            if not self.edited_text or not self.edited_text.strip():
                raise ValueError("an edited correction requires edited_text")
        elif self.edited_text is not None:
            raise ValueError("edited_text is only meaningful when outcome is 'edited'")
        if self.edited_text is not None and len(self.edited_text) > MAX_EDITED_TEXT_CHARS:
            raise ValueError(f"edited_text is limited to {MAX_EDITED_TEXT_CHARS} characters")


def _unique_clean(values: list[str], limit: int) -> list[str]:
    """Deduplicate case-insensitively while keeping the caller's order.

    Order matters: callers pass most-relevant-first, and sorting here would
    silently discard that ranking when the list is trimmed.
    """
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) == limit:
            break
    return out


def _clip(value: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    return " ".join((value or "").split())[:limit]
