"""Operational mnemonic strength (issue #185 TODO 3)."""
from __future__ import annotations

from app.domain.services.mnemonic_scoring import (
    evaluate_mnemonic_strength,
    should_replace_mnemonic,
)


def test_insufficient_samples_is_neither_strong_nor_weak():
    strength = evaluate_mnemonic_strength(delayed_correct=1, delayed_total=1, learner_score=0)
    assert strength.verdict == "insufficient_data"
    assert strength.delayed_accuracy is None


def test_weak_delayed_accuracy_is_weak():
    strength = evaluate_mnemonic_strength(delayed_correct=1, delayed_total=4, learner_score=0)
    assert strength.verdict == "weak"
    assert strength.delayed_accuracy == 0.25


def test_strong_delayed_accuracy_is_strong():
    strength = evaluate_mnemonic_strength(delayed_correct=4, delayed_total=5, learner_score=0)
    assert strength.verdict == "strong"


def test_a_negative_learner_vote_is_decisive_regardless_of_sample_size():
    """TODO 4: the learner can challenge a conclusion outright."""
    strength = evaluate_mnemonic_strength(delayed_correct=10, delayed_total=10, learner_score=-1)
    assert strength.verdict == "weak"


def test_replacement_requires_a_weak_verdict_or_an_explicit_request():
    strong = evaluate_mnemonic_strength(delayed_correct=5, delayed_total=5, learner_score=0)
    weak = evaluate_mnemonic_strength(delayed_correct=0, delayed_total=5, learner_score=0)

    assert should_replace_mnemonic(strong, explicit_request=False) is False
    assert should_replace_mnemonic(strong, explicit_request=True) is True
    assert should_replace_mnemonic(weak, explicit_request=False) is True


def test_insufficient_data_does_not_authorize_replacement_on_its_own():
    """TODO 3's own verify clause: an AI-generated note cannot get replaced
    just because there isn't much evidence yet — that would let "the AI
    thinks a fresh one sounds better" through the back door."""
    insufficient = evaluate_mnemonic_strength(delayed_correct=0, delayed_total=1, learner_score=0)
    assert should_replace_mnemonic(insufficient, explicit_request=False) is False
