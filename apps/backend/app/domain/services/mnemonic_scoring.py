"""Operational mnemonic strength (issue #185 TODO 3).

Whether a mnemonic gets replaced is decided from measured signals — delayed
recall while it was the word's active note, a negative learner vote, and
reuse — never by asking an AI whether the text "sounds good". `is_ai_generated`
is deliberately absent from every signal below: TODO 3's own verify clause is
that AI-generated prose alone cannot raise the score.

Pure and deterministic: no repository, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

# TODO 3: replace only after weak outcomes, not a single unlucky review.
MIN_DELAYED_SAMPLES = 3
WEAK_ACCURACY_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class MnemonicStrength:
    """"works well" / "works poorly" / "not enough evidence" — the same
    three-way split #186 TODO 4 asks the Learning DNA UI to show, applied
    here to one mnemonic rather than a whole intervention technique."""

    verdict: str  # "strong" | "weak" | "insufficient_data"
    delayed_accuracy: float | None
    sample_size: int


def evaluate_mnemonic_strength(
    *, delayed_correct: int, delayed_total: int, learner_score: int
) -> MnemonicStrength:
    """`delayed_correct`/`delayed_total` count reviews answered after the
    mnemonic was attached, excluding same-session repeats (the same
    "meaningful gap" reasoning `diagnosis_engine.py` already applies).
    `learner_score` is `MnemonicNote.score` (upvotes - downvotes) — an
    explicit negative rating is decisive on its own, independent of sample
    size, matching TODO 4's "let the learner ... challenge conclusions."
    """
    if learner_score < 0:
        return MnemonicStrength(verdict="weak", delayed_accuracy=None, sample_size=delayed_total)
    if delayed_total < MIN_DELAYED_SAMPLES:
        return MnemonicStrength(verdict="insufficient_data", delayed_accuracy=None, sample_size=delayed_total)
    accuracy = delayed_correct / delayed_total
    verdict = "weak" if accuracy < WEAK_ACCURACY_THRESHOLD else "strong"
    return MnemonicStrength(verdict=verdict, delayed_accuracy=accuracy, sample_size=delayed_total)


def should_replace_mnemonic(strength: MnemonicStrength, *, explicit_request: bool) -> bool:
    """TODO 3's own verify clause: an AI's opinion of its own prose can
    never be the reason. Only a weak measured outcome or the learner
    asking outright allows a replacement."""
    if explicit_request:
        return True
    return strength.verdict == "weak"
