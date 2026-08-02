"""Role-play attempts over HTTP (issue #136).

The claim tested hardest is the refusal: an attempt too short to judge gets no
score, and the model is not even asked.
"""
from __future__ import annotations

import pytest

from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.scenarios import MIN_LEARNER_TURNS_TO_SCORE


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


class _Judge:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload if payload is not None else {
            "scores": {
                "vocabulary": {"score": 70, "comment": "good range"},
                "grammar": {"score": 60, "comment": ""},
                "fluency": {"score": 80, "comment": ""},
                "task_completion": {"score": 90, "comment": ""},
            },
            "summary": "Solid attempt.",
            "goals_met": ["Order food and drink"],
        }
        self.error = error
        self.calls = 0

    async def evaluate_scenario(self, scenario, transcript):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload

    async def converse(self, context, learner_message):
        return {"reply": "Claro."}


class _use:
    """Override just the AI provider — clearing all overrides would drop the
    database override the client fixture installs."""

    def __init__(self, provider):
        self.provider = provider

    def __enter__(self):
        from app.api import deps
        from app.main import app

        self.app = app
        self.key = deps.get_ai_provider
        app.dependency_overrides[self.key] = lambda: self.provider
        return self

    def __exit__(self, *exc):
        self.app.dependency_overrides.pop(self.key, None)
        return False


def _start(client, headers, key="restaurant"):
    resp = client.post(
        "/api/v1/scenarios/attempts",
        json={"scenario_key": key, "target_language": "Spanish", "difficulty": "steady"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _say(client, headers, session_id, text):
    return client.post(
        f"/api/v1/conversations/{session_id}/message", json={"text": text}, headers=headers
    )


def _talk(client, headers, session_id, turns: int, provider):
    with _use(provider):
        for index in range(turns):
            _say(client, headers, session_id, f"mensaje {index}")


# --- The catalog ------------------------------------------------------------


def test_the_catalog_is_listed(client):
    body = client.get("/api/v1/scenarios").json()

    assert {s["key"] for s in body} >= {"restaurant", "job_interview", "airport"}


def test_the_catalog_never_reveals_the_tutors_instruction(client):
    """The learner is shown a briefing, not the prompt the model is given."""
    body = client.get("/api/v1/scenarios").json()

    assert all("tutor_role" not in scenario for scenario in body)


def test_every_listed_scenario_states_its_goals(client):
    body = client.get("/api/v1/scenarios").json()

    assert all(scenario["goals"] for scenario in body)


# --- Starting ---------------------------------------------------------------


def test_starting_an_attempt_creates_a_conversation_to_talk_in(client, headers):
    attempt = _start(client, headers)

    assert attempt["session_id"]
    assert client.get(f"/api/v1/conversations/{attempt['session_id']}", headers=headers).status_code == 200


def test_an_unknown_scenario_is_a_404(client, headers):
    resp = client.post(
        "/api/v1/scenarios/attempts",
        json={"scenario_key": "underwater_basket_weaving", "target_language": "Spanish"},
        headers=headers,
    )

    assert resp.status_code == 404


def test_starting_requires_authentication(client):
    resp = client.post(
        "/api/v1/scenarios/attempts",
        json={"scenario_key": "restaurant", "target_language": "Spanish"},
    )
    assert resp.status_code == 401


# --- Too short to judge -----------------------------------------------------


def test_a_short_attempt_is_not_scored_and_the_model_is_not_asked(client, headers):
    """Scoring three messages produces a confident number the learner will
    believe because it looks precise."""
    attempt = _start(client, headers)
    judge = _Judge()
    _talk(client, headers, attempt["session_id"], 1, judge)

    with _use(judge):
        body = client.post(
            f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers
        ).json()

    assert body["evaluation"]["scored"] is False
    assert body["evaluation"]["overall"] is None
    assert judge.calls == 0


def test_the_refusal_says_what_would_make_it_scoreable(client, headers):
    attempt = _start(client, headers)
    judge = _Judge()

    with _use(judge):
        body = client.post(
            f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers
        ).json()

    assert str(MIN_LEARNER_TURNS_TO_SCORE) in body["evaluation"]["detail"]


# --- A scored attempt -------------------------------------------------------


def test_a_long_enough_attempt_is_scored(client, headers):
    attempt = _start(client, headers)
    judge = _Judge()
    _talk(client, headers, attempt["session_id"], MIN_LEARNER_TURNS_TO_SCORE, judge)

    with _use(judge):
        body = client.post(
            f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers
        ).json()

    assert body["evaluation"]["scored"] is True
    assert body["evaluation"]["overall"] == 75
    assert body["finished_at"] is not None


def test_only_goals_the_scenario_has_are_reported(client, headers):
    attempt = _start(client, headers)
    judge = _Judge()
    judge.payload = {
        **judge.payload,
        "goals_met": ["Order food and drink", "Pilot the aircraft"],
    }
    _talk(client, headers, attempt["session_id"], MIN_LEARNER_TURNS_TO_SCORE, judge)

    with _use(judge):
        body = client.post(
            f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers
        ).json()

    assert body["evaluation"]["goals_met"] == ["Order food and drink"]


def test_an_unreachable_model_leaves_the_attempt_unscored_rather_than_failing(client, headers):
    attempt = _start(client, headers)
    talker = _Judge()
    _talk(client, headers, attempt["session_id"], MIN_LEARNER_TURNS_TO_SCORE, talker)

    with _use(_Judge(error=AIProviderUnavailableError("model is starting"))):
        resp = client.post(f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["evaluation"]["scored"] is False


def test_no_provider_leaves_the_attempt_unscored(client, headers):
    attempt = _start(client, headers)
    talker = _Judge()
    _talk(client, headers, attempt["session_id"], MIN_LEARNER_TURNS_TO_SCORE, talker)

    with _use(None):
        body = client.post(
            f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers
        ).json()

    assert body["evaluation"]["scored"] is False
    assert "not configured" in body["evaluation"]["detail"]


def test_finishing_ends_the_conversation(client, headers):
    attempt = _start(client, headers)
    judge = _Judge()
    _talk(client, headers, attempt["session_id"], MIN_LEARNER_TURNS_TO_SCORE, judge)

    with _use(judge):
        client.post(f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers)

    conversation = client.get(
        f"/api/v1/conversations/{attempt['session_id']}", headers=headers
    ).json()
    assert conversation["ended_at"] is not None


# --- Ownership --------------------------------------------------------------


def test_another_accounts_attempt_is_a_404(client, auth_headers):
    alex = auth_headers()
    attempt = _start(client, alex)

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get(f"/api/v1/scenarios/attempts/{attempt['id']}", headers=sam).status_code == 404
    assert client.post(
        f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=sam
    ).status_code == 404


def test_attempts_are_listed_per_account(client, auth_headers):
    alex = auth_headers()
    _start(client, alex)
    sam = auth_headers(username="sam", email="sam@example.com")

    assert len(client.get("/api/v1/scenarios/attempts", headers=alex).json()) == 1
    assert client.get("/api/v1/scenarios/attempts", headers=sam).json() == []


def test_deleting_the_conversation_takes_the_attempt_with_it(client, headers, db_session):
    """The attempt is unreadable without its transcript. Left in place it would
    be a foreign-key violation on Postgres and a silently orphaned row on
    SQLite — the divergence the tenant-isolation audit exists to catch."""
    from app.infrastructure.repositories import SqlAlchemyScenarioAttemptRepository

    attempt = _start(client, headers)

    assert client.delete(
        f"/api/v1/conversations/{attempt['session_id']}", headers=headers
    ).status_code == 204
    assert SqlAlchemyScenarioAttemptRepository(db_session).get(attempt["id"]) is None
