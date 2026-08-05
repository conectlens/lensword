"""Learning paths from a stated goal (issue #137).

Two things are being defended. A model asked for a plan will sometimes return
sixty steps, or one with an empty title, or a target of five thousand words —
so the plan is bounded before it is stored. And progress is measured from the
learner's actual deck rather than remembered, so a progress bar can never
disagree with the vocabulary list beside it.
"""
from __future__ import annotations

import pytest

from app.domain.services.learning_path import (
    MAX_MILESTONES,
    MAX_WORDS_PER_MILESTONE,
    MIN_WORDS_PER_MILESTONE,
    InvalidPlanError,
    MilestonePlan,
    clean_goal,
    measure,
    validate_plan,
)


def _entry(title="Order food", topic="restaurant", count=10, **extra):
    return {"title": title, "topic": topic, "target_word_count": count, **extra}


def _plan(title="Order food", topic="restaurant", count=10, level=None):
    return MilestonePlan(
        title=title, description="", topic=topic, target_word_count=count, cefr_level=level
    )


# --- Bounding a model's plan ------------------------------------------------


def test_a_reasonable_plan_survives_intact():
    plans = validate_plan([_entry(title="A"), _entry(title="B")])

    assert [p.title for p in plans] == ["A", "B"]


def test_an_over_long_plan_is_truncated():
    """A path longer than a handful stops being a plan and becomes a syllabus
    nobody opens."""
    plans = validate_plan([_entry(title=f"Step {i}") for i in range(30)])

    assert len(plans) == MAX_MILESTONES


def test_a_milestone_with_no_title_is_dropped():
    """Not something a learner can act on."""
    plans = validate_plan([_entry(title="A"), _entry(title="  "), _entry(title="B")])

    assert [p.title for p in plans] == ["A", "B"]


def test_a_milestone_with_no_topic_is_dropped():
    """It cannot be measured, so it would be a card that never moves."""
    plans = validate_plan([_entry(title="A"), _entry(title="B", topic=""), _entry(title="C")])

    assert [p.title for p in plans] == ["A", "C"]


def test_a_plan_with_nothing_usable_raises_rather_than_returning_empty():
    """An empty path presented as a plan is worse than an error — the learner
    cannot tell whether it means "no steps needed" or "this went wrong"."""
    with pytest.raises(InvalidPlanError):
        validate_plan([{"title": "", "topic": ""}])


def test_a_single_milestone_is_not_a_path():
    with pytest.raises(InvalidPlanError):
        validate_plan([_entry()])


def test_nothing_at_all_raises():
    with pytest.raises(InvalidPlanError):
        validate_plan([])


def test_junk_entries_are_ignored_rather_than_crashing():
    plans = validate_plan([_entry(title="A"), "not a dict", None, _entry(title="B")])

    assert len(plans) == 2


# --- Bounding the numbers ---------------------------------------------------


def test_an_absurd_word_target_is_capped():
    """A model cannot set a target nobody reaches."""
    plans = validate_plan([_entry(count=5000), _entry(title="B")])

    assert plans[0].target_word_count == MAX_WORDS_PER_MILESTONE


def test_a_zero_target_becomes_the_floor():
    """Zero would make the milestone complete the moment it was created."""
    plans = validate_plan([_entry(count=0), _entry(title="B")])

    assert plans[0].target_word_count == MIN_WORDS_PER_MILESTONE


def test_an_unparseable_target_becomes_the_floor():
    plans = validate_plan([_entry(count="lots"), _entry(title="B")])

    assert plans[0].target_word_count == MIN_WORDS_PER_MILESTONE


def test_an_unrecognised_cefr_level_is_dropped():
    """"Intermediate" is not a CEFR level, and storing it would put a value in
    the column that nothing else can compare against."""
    plans = validate_plan([_entry(cefr_level="Intermediate"), _entry(title="B")])

    assert plans[0].cefr_level is None


def test_a_real_cefr_level_is_kept_and_normalised():
    plans = validate_plan([_entry(cefr_level="b1"), _entry(title="B")])

    assert plans[0].cefr_level == "B1"


def test_long_text_is_truncated_rather_than_rejected():
    plans = validate_plan([_entry(title="x" * 500), _entry(title="B")])

    assert len(plans[0].title) <= 120


# --- The goal ---------------------------------------------------------------


def test_a_goal_is_normalised():
    assert clean_goal("  order   food  in Spain ") == "order food in Spain"


def test_an_empty_goal_is_refused():
    with pytest.raises(InvalidPlanError):
        clean_goal("   ")


def test_an_enormous_goal_is_bounded():
    """It is stored, displayed, and sent to a model — an unbounded goal is a
    way to push everything else out of a prompt."""
    assert len(clean_goal("x" * 5000)) <= 500


# --- Measuring progress -----------------------------------------------------


def test_a_milestone_is_complete_when_the_words_are_held():
    progress = measure("goal", [_plan(count=5)], {"restaurant": (5, 2)})

    assert progress.milestones[0].complete is True


def test_a_milestone_short_of_target_is_not_complete():
    progress = measure("goal", [_plan(count=5)], {"restaurant": (4, 4)})

    assert progress.milestones[0].complete is False


def test_a_topic_the_learner_has_nothing_in_reads_as_zero():
    progress = measure("goal", [_plan(topic="astrophysics")], {})

    assert progress.milestones[0].words_held == 0
    assert progress.milestones[0].share == 0.0


def test_topic_matching_ignores_case():
    progress = measure("goal", [_plan(topic="Restaurant")], {"restaurant": (10, 0)})

    assert progress.milestones[0].words_held == 10


def test_exceeding_the_target_does_not_exceed_full():
    """A learner who added twice the target has finished the milestone, not
    finished it twice."""
    progress = measure("goal", [_plan(count=5)], {"restaurant": (50, 10)})

    assert progress.milestones[0].share == 1.0


def test_overall_progress_counts_milestones_not_words():
    """A path with one huge step and four small ones should not read as 80%
    done when the big one is untouched."""
    plans = [_plan(topic="a", count=5), _plan(topic="b", count=5)]
    progress = measure("goal", plans, {"a": (5, 0)})

    assert progress.share == 0.5
    assert progress.completed_count == 1


def test_the_next_milestone_is_the_first_unfinished_one():
    """What the learner is actually being asked to do."""
    plans = [_plan(title="A", topic="a", count=5), _plan(title="B", topic="b", count=5)]
    progress = measure("goal", plans, {"a": (5, 0)})

    assert progress.next_milestone.title == "B"


def test_a_finished_path_has_no_next_milestone():
    plans = [_plan(topic="a", count=1), _plan(topic="b", count=1)]
    progress = measure("goal", plans, {"a": (1, 0), "b": (1, 0)})

    assert progress.next_milestone is None
    assert progress.share == 1.0


def test_an_empty_path_reports_zero_rather_than_dividing_by_nothing():
    progress = measure("goal", [], {})

    assert progress.share == 0.0
    assert progress.next_milestone is None


def test_mastered_counts_travel_alongside_held():
    """Holding a word and recalling it are different claims, and a path that
    reported only the first would overstate what the learner can do."""
    progress = measure("goal", [_plan(count=10)], {"restaurant": (10, 3)})

    assert (progress.milestones[0].words_held, progress.milestones[0].words_mastered) == (10, 3)
