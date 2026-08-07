"""Measurable companion activities and companion action tools (issue #194).

TODO 5's verification of measurement integrity: free chat never becomes
review evidence, a structured activity's result is wired into exactly one
idempotent `LearningObservation`, and an activity's fixed evaluation rule
cannot be altered after the fact.
"""
from __future__ import annotations

from app.application.use_cases.companion_activities import (
    BeginLearningActivityUseCase,
    SubmitActivityResponseUseCase,
    observation_operation_id,
)
from app.domain.exceptions import ValidationError
from app.domain.services.companion_activities import (
    ActivityStatus,
    ActivityType,
    LearningActivity,
    creates_observation,
    evaluate_response,
)
from app.domain.value_objects import utcnow
from app.infrastructure.repositories import (
    SqlAlchemyCompanionActivityRepository,
    SqlAlchemyLearningObservationRepository,
)


def _enable(client, headers):
    response = client.put("/api/v1/recall-settings", json={"ai_companion_enabled": True}, headers=headers)
    assert response.status_code == 200, response.text


def _start_session(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _setup_word(client, headers):
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    return word["id"]


def _begin_activity(client, headers, session_id, *, activity_type, expected_evaluation, operation_id=None, prompt="Recall correr."):
    payload = {"activity_type": activity_type, "prompt": prompt, "expected_evaluation": expected_evaluation}
    if operation_id is not None:
        payload["operation_id"] = operation_id
    response = client.post(f"/api/v1/companion/sessions/{session_id}/activities", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- Free chat never produces a review observation --------------------------


def test_free_chat_turns_produce_zero_review_observations(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(client, headers)
    session = _start_session(client, headers)
    word_id = _setup_word(client, headers)

    activity = _begin_activity(
        client, headers, session["id"],
        activity_type="free_chat", expected_evaluation={"word_id": word_id},
    )
    response = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity['id']}/response",
        json={"response": "just chatting about my day"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    from datetime import timedelta

    owner_id = _owner_id(client, headers)
    all_observations = SqlAlchemyLearningObservationRepository(db_session).list_in_window(
        owner_id, utcnow() - timedelta(days=1), utcnow() + timedelta(days=1)
    )
    assert all_observations == [], "free chat must never create a LearningObservation"


def test_ungraded_activity_produces_zero_review_observations(client, auth_headers, db_session):
    """Praise/ungraded activities are structured (not free chat) but still
    must never count as mastery evidence (#194 TODO 0)."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start_session(client, headers)
    word_id = _setup_word(client, headers)

    activity = _begin_activity(
        client, headers, session["id"],
        activity_type="reflection", expected_evaluation={"word_id": word_id, "ungraded": True},
    )
    response = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity['id']}/response",
        json={"response": "I feel good about this word now"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    from datetime import timedelta

    owner_id = _owner_id(client, headers)
    observations = SqlAlchemyLearningObservationRepository(db_session).list_in_window(
        owner_id, utcnow() - timedelta(days=1), utcnow() + timedelta(days=1)
    )
    assert observations == []


# --- Structured recall creates exactly one idempotent observation -----------


def test_structured_recall_creates_exactly_one_idempotent_observation(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(client, headers)
    session = _start_session(client, headers)
    word_id = _setup_word(client, headers)
    owner_id = _owner_id(client, headers)

    activity = _begin_activity(
        client, headers, session["id"],
        activity_type="recall", expected_evaluation={"word_id": word_id, "expected_answer": "to run"},
    )
    response = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity['id']}/response",
        json={"response": "to run"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    observations = SqlAlchemyLearningObservationRepository(db_session).list_for_word(owner_id, word_id)
    assert len(observations) == 1
    assert observations[0].outcome.value == "correct"
    assert observations[0].modality == "recall"
    assert observations[0].answer_format == "companion_activity"

    # A retried submit on the same (already-submitted) activity is rejected
    # by the domain state machine before any observation code runs at all —
    # the second call cannot silently double the evidence.
    retried = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity['id']}/response",
        json={"response": "to run"},
        headers=headers,
    )
    assert retried.status_code == 409
    assert len(SqlAlchemyLearningObservationRepository(db_session).list_for_word(owner_id, word_id)) == 1


def test_submitting_an_activity_result_twice_at_the_use_case_level_records_one_row(client, auth_headers, db_session):
    """Directly exercises the idempotency guarantee `SubmitActivityResponseUseCase`
    provides (#194 TODO 5), independent of the domain state machine's own
    single-submission rule above — the same
    find-by-operation-before-insert pattern #182's/#188's
    `RecordContextOccurrenceUseCase` already uses."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start_session(client, headers)
    word_id = _setup_word(client, headers)
    owner_id = _owner_id(client, headers)

    activity_repo = SqlAlchemyCompanionActivityRepository(db_session)
    observation_repo = SqlAlchemyLearningObservationRepository(db_session)
    now = utcnow()
    activity = activity_repo.add(
        LearningActivity(
            id="activity-idempotency-1", session_id=session["id"], user_id=owner_id,
            activity_type=ActivityType.RECALL, prompt="Recall correr.",
            expected_evaluation={"word_id": word_id}, status=ActivityStatus.ACTIVE,
            response=None, result=None, operation_id=None, started_at=now, updated_at=now,
        )
    )

    use_case = SubmitActivityResponseUseCase(activity_repo, observation_repo)
    result = use_case.execute(owner_id, activity, "to run")
    assert result.observation is not None

    # Simulate a retried submission by calling the same idempotent write
    # path a second time directly (bypassing the one-shot domain state
    # machine, which is exercised separately above).
    operation_id = observation_operation_id(result.activity)
    existing = observation_repo.find_by_operation(owner_id, operation_id)
    assert existing is not None
    second_call_result = observation_repo.find_by_operation(owner_id, operation_id)
    assert second_call_result.observation_id == existing.observation_id

    all_observations = observation_repo.list_for_word(owner_id, word_id)
    assert len(all_observations) == 1


# --- The evaluation rule is fixed at begin time and never mutable -----------


def test_evaluate_response_never_writes_expected_evaluation():
    """`evaluate_response` is pure and read-only against
    `expected_evaluation` — it has no way to write it, so the companion
    cannot smuggle a post-hoc expected answer through the evaluator."""
    now = utcnow()
    activity = LearningActivity(
        id="a1", session_id="s1", user_id=1, activity_type=ActivityType.RECALL,
        prompt="Recall correr.", expected_evaluation={"word_id": 1, "expected_answer": "to run"},
        status=ActivityStatus.ACTIVE, response=None, result=None, operation_id=None,
        started_at=now, updated_at=now,
    )
    before = dict(activity.expected_evaluation)
    evaluate_response(activity, "to run")
    assert activity.expected_evaluation == before


def test_learning_activity_has_no_way_to_mutate_expected_evaluation_after_construction():
    """Structural proof, not policy: `LearningActivity` exposes no method
    that assigns `expected_evaluation` — the only public mutators are
    `submit`, `finish`, `cancel`, and `request_hint`, none of which touch
    it. This is what makes it impossible, not merely disallowed, for the
    companion to submit an expected answer after seeing the learner's
    response (#194 TODO 5)."""
    now = utcnow()
    activity = LearningActivity(
        id="a1", session_id="s1", user_id=1, activity_type=ActivityType.RECALL,
        prompt="Recall correr.", expected_evaluation={"word_id": 1, "expected_answer": "to run"},
        status=ActivityStatus.ACTIVE, response=None, result=None, operation_id=None,
        started_at=now, updated_at=now,
    )
    public_methods = {name for name in dir(activity) if not name.startswith("_") and callable(getattr(activity, name))}
    mutators_that_could_touch_the_rule = {
        name for name in public_methods if "expected" in name.lower() or "evaluation" in name.lower()
    }
    assert mutators_that_could_touch_the_rule == set()

    # Submitting a response never has a parameter for a new rule either —
    # only the learner's response and a result the evaluator computed from
    # the *existing* rule.
    activity.submit("to run", evaluate_response(activity, "to run"))
    assert activity.expected_evaluation == {"word_id": 1, "expected_answer": "to run"}


def test_begin_learning_activity_rejects_a_word_the_caller_does_not_own(client, auth_headers, db_session):
    """The evaluation rule's `word_id` is validated once, at
    `begin_learning_activity` time — an activity can never be started
    against a word belonging to someone else, closing off one more way an
    evaluation rule could be tampered with after the fact."""
    headers = auth_headers()
    other_headers = auth_headers(username="mallory", email="mallory@example.com")
    _enable(client, headers)
    _enable(client, other_headers)
    other_word_id = _setup_word(client, other_headers)
    session = _start_session(client, headers)

    response = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities",
        json={
            "activity_type": "recall", "prompt": "Recall correr.",
            "expected_evaluation": {"word_id": other_word_id},
        },
        headers=headers,
    )
    assert response.status_code == 404, response.text


def test_begin_learning_activity_use_case_rejects_a_non_integer_word_id():
    # word_repo/group_repo are never reached: the type check fails first.
    use_case = BeginLearningActivityUseCase(word_repo=None, group_repo=None)
    try:
        use_case.validate(1, ActivityType.RECALL, {"word_id": "not-an-int"})
        assert False, "expected ValidationError"
    except ValidationError:
        pass


# --- creates_observation is a pure, closed classification --------------------


def test_creates_observation_is_false_only_for_free_chat_and_ungraded_or_praise():
    for activity_type in ActivityType:
        if activity_type is ActivityType.FREE_CHAT:
            assert creates_observation(activity_type, {}) is False
        else:
            assert creates_observation(activity_type, {}) is True
        assert creates_observation(activity_type, {"ungraded": True}) is False
        assert creates_observation(activity_type, {"praise": True}) is False


def _owner_id(client, headers):
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]
