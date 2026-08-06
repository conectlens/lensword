"""Scenario catalog and attempt scoring (issue #136).

The refusals matter most: an attempt too short to judge is not given a number,
and a dimension the model stayed silent about is absent rather than zero.
"""
from __future__ import annotations

import pytest

from app.domain.services.scenarios import (
    CATALOG,
    MAX_SCORE,
    MIN_LEARNER_CHARACTERS_TO_SCORE,
    MIN_LEARNER_TURNS_TO_SCORE,
    Evaluation,
    ScoreDimension,
    can_score,
    get_scenario,
    unscored,
    validate_evaluation,
)

RESTAURANT = get_scenario("restaurant")


def _raw(**over):
    base = {
        "scores": {
            "vocabulary": {"score": 70, "comment": "good range"},
            "grammar": {"score": 60, "comment": ""},
            "fluency": {"score": 80, "comment": ""},
            "task_completion": {"score": 90, "comment": ""},
        },
        "summary": "Solid attempt.",
        "goals_met": ["Order food and drink"],
    }
    base.update(over)
    return base


# --- The catalog ------------------------------------------------------------


def test_the_catalog_covers_the_scenarios_the_issue_named():
    keys = {scenario.key for scenario in CATALOG}

    assert keys == {
        "job_interview",
        "airport",
        "restaurant",
        "customer_support",
        "meeting",
        "presentation",
        "travel_emergency",
    }


def test_every_scenario_has_goals_to_be_scored_against():
    """Task completion is the dimension a free conversation cannot have, and it
    needs something concrete to judge."""
    assert all(scenario.goals for scenario in CATALOG)


def test_every_scenario_separates_the_briefing_from_the_tutor_role():
    """The learner is never shown the instruction given to the model."""
    for scenario in CATALOG:
        assert scenario.briefing and scenario.tutor_role
        assert scenario.tutor_role not in scenario.briefing


def test_lookup_ignores_case_and_space():
    assert get_scenario("  RESTAURANT ") is RESTAURANT


def test_an_unknown_scenario_is_none_rather_than_a_guess():
    assert get_scenario("underwater_basket_weaving") is None


# --- Too short to judge -----------------------------------------------------


def test_a_short_attempt_cannot_be_scored():
    """A confident 72/100 derived from one exchange is a figure the learner will
    believe because it looks precise."""
    assert can_score(1, 100) is False
    assert can_score(MIN_LEARNER_TURNS_TO_SCORE - 1, 100) is False


def test_a_long_enough_attempt_can_be_scored():
    assert can_score(MIN_LEARNER_TURNS_TO_SCORE, MIN_LEARNER_CHARACTERS_TO_SCORE) is True


def test_enough_turns_but_too_little_substance_cannot_be_scored():
    """Issue #213: four one-word non-answers ("queso", "no se", "mmm",
    "banana carro azul" — 31 characters, the exact transcript that scored
    82/100 against a real model) clear the turn-count gate but not this
    one — a turn count alone cannot tell that apart from four short but
    real sentences."""
    assert can_score(MIN_LEARNER_TURNS_TO_SCORE, MIN_LEARNER_CHARACTERS_TO_SCORE - 1) is False


def test_four_short_but_real_turns_can_be_scored():
    """"Hola" / "Una mesa para dos, por favor" / "Sí, el especial" /
    "Gracias" — 54 characters across four genuine turns — must not be
    caught by the same gate that refuses four throwaway non-answers."""
    assert can_score(MIN_LEARNER_TURNS_TO_SCORE, 54) is True


def test_an_unscored_evaluation_carries_a_reason_rather_than_zeroes():
    evaluation = unscored("Only two turns — not enough to judge.")

    assert evaluation.scored is False
    assert evaluation.overall is None
    assert evaluation.scores == []
    assert "not enough" in evaluation.detail


# --- Validating the judgement ----------------------------------------------


def test_a_complete_evaluation_is_accepted():
    evaluation = validate_evaluation(_raw(), RESTAURANT)

    assert evaluation.scored is True
    assert {s.dimension for s in evaluation.scores} == set(ScoreDimension)


def test_scores_are_clamped_rather_than_trusted():
    evaluation = validate_evaluation(
        _raw(scores={"vocabulary": 900, "grammar": -50, "fluency": 50, "task_completion": 50}),
        RESTAURANT,
    )

    by_dimension = {s.dimension: s.score for s in evaluation.scores}
    assert by_dimension[ScoreDimension.VOCABULARY] == MAX_SCORE
    assert by_dimension[ScoreDimension.GRAMMAR] == 0


def test_a_missing_dimension_is_absent_rather_than_zero():
    """Zero is a claim that the learner did badly, and we would be making it on
    the model's silence."""
    evaluation = validate_evaluation(_raw(scores={"vocabulary": 70}), RESTAURANT)

    assert [s.dimension for s in evaluation.scores] == [ScoreDimension.VOCABULARY]


def test_an_evaluation_with_no_usable_scores_is_refused():
    with pytest.raises(ValueError):
        validate_evaluation(_raw(scores={}), RESTAURANT)


def test_a_non_dict_evaluation_is_refused():
    with pytest.raises(ValueError):
        validate_evaluation(["nope"], RESTAURANT)


def test_a_bare_number_is_accepted_as_a_score():
    """Models answer both shapes; rejecting the simpler one would fail turns
    for a formatting difference."""
    evaluation = validate_evaluation(_raw(scores={"grammar": 55}), RESTAURANT)

    assert evaluation.scores[0].score == 55


def test_an_unparseable_score_is_dropped_not_defaulted():
    evaluation = validate_evaluation(
        _raw(scores={"vocabulary": "excellent", "grammar": 60}), RESTAURANT
    )

    assert [s.dimension for s in evaluation.scores] == [ScoreDimension.GRAMMAR]


# --- Goals ------------------------------------------------------------------


def test_only_goals_this_scenario_actually_has_are_reported():
    """A goal nobody set would show the learner a task they were never asked to
    do."""
    evaluation = validate_evaluation(
        _raw(goals_met=["Order food and drink", "Pilot the aircraft"]), RESTAURANT
    )

    assert evaluation.goals_met == ["Order food and drink"]


def test_goal_matching_ignores_case():
    evaluation = validate_evaluation(_raw(goals_met=["order food and drink"]), RESTAURANT)

    assert evaluation.goals_met == ["Order food and drink"]


def test_no_goals_met_is_an_empty_list_not_an_error():
    evaluation = validate_evaluation(_raw(goals_met=[]), RESTAURANT)

    assert evaluation.goals_met == []


def test_junk_in_the_goals_list_is_ignored():
    evaluation = validate_evaluation(_raw(goals_met=[None, 7, "Ask for the bill"]), RESTAURANT)

    assert evaluation.goals_met == ["Ask for the bill"]


# --- Overall ----------------------------------------------------------------


def test_overall_is_the_mean_of_what_was_scored():
    evaluation = validate_evaluation(
        _raw(scores={"vocabulary": 60, "grammar": 80, "fluency": 70, "task_completion": 90}),
        RESTAURANT,
    )

    assert evaluation.overall == 75


def test_overall_is_none_when_nothing_was_scored():
    assert Evaluation().overall is None


def test_a_long_summary_is_truncated_rather_than_rejected():
    evaluation = validate_evaluation(_raw(summary="x" * 5000), RESTAURANT)

    assert len(evaluation.summary) <= 600
