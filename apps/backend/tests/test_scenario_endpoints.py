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
        self.key = deps.get_ai_provider_for_user
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
    # Long enough, across MIN_LEARNER_TURNS_TO_SCORE turns, to clear issue
    # #213's MIN_LEARNER_CHARACTERS_TO_SCORE gate too — these tests are
    # about the scoring flow, not about exercising that gate itself (see
    # test_scenarios.py for that), so the fixture content must not
    # accidentally trip it.
    with _use(provider):
        for index in range(turns):
            _say(client, headers, session_id, f"este es un mensaje de prueba numero {index}")


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


def test_enough_turns_but_too_little_substance_is_not_scored_and_the_model_is_not_asked(client, headers):
    """Issue #213: a real model scored this exact transcript — four
    one-word non-answers — 82/100 on one run, with a fabricated summary
    claiming things that never happened. Refused before the model is
    asked at all, the same way a too-short attempt already was."""
    attempt = _start(client, headers)
    judge = _Judge()
    with _use(judge):
        for text in ("queso", "no se", "mmm", "banana carro azul"):
            _say(client, headers, attempt["session_id"], text)

        body = client.post(
            f"/api/v1/scenarios/attempts/{attempt['id']}/finish", headers=headers
        ).json()

    assert body["evaluation"]["scored"] is False
    assert body["evaluation"]["overall"] is None
    assert judge.calls == 0


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


# --- Scenario vocabulary (issue #144) ---------------------------------------


def _group(client, headers) -> int:
    return client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    ).json()["id"]


def _word(client, headers, group_id: int, term: str, topics=(), synonyms=()):
    word_id = client.post(
        f"/api/v1/groups/{group_id}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
        headers=headers,
    ).json()["id"]
    add = [{"kind": "topic", "value": t} for t in topics]
    add += [{"kind": "synonym", "value": s} for s in synonyms]
    if add:
        client.patch(
            f"/api/v1/words/{word_id}/associations",
            json={"add": add, "remove": []},
            headers=headers,
        )
    return word_id


def test_words_on_the_scenarios_topics_are_suggested(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "camarero", topics=["restaurant"])

    body = client.get("/api/v1/scenarios/restaurant/vocabulary", headers=headers).json()

    assert [w["term"] for w in body["on_topic"]] == ["camarero"]


def test_only_words_the_learner_already_has_are_suggested(client, headers):
    """Suggesting vocabulary they do not have would be a shopping list dressed
    as preparation."""
    body = client.get("/api/v1/scenarios/restaurant/vocabulary", headers=headers).json()

    assert body["on_topic"] == []
    assert body["related"] == []


def test_a_thin_deck_is_said_plainly_rather_than_shown_as_a_short_list(client, headers):
    """A two-word list looks like the feature is broken rather than like the
    deck is thin."""
    group_id = _group(client, headers)
    _word(client, headers, group_id, "camarero", topics=["restaurant"])

    body = client.get("/api/v1/scenarios/restaurant/vocabulary", headers=headers).json()

    assert body["sparse"] is True
    assert "Add a few" in body["detail"]


def test_a_related_word_from_another_topic_still_surfaces(client, headers):
    """Reached through the knowledge graph rather than topic tags, so a word
    filed elsewhere but linked to an on-topic one is not missed."""
    group_id = _group(client, headers)
    _word(client, headers, group_id, "camarero", topics=["restaurant"], synonyms=["mesero"])
    _word(client, headers, group_id, "mesero", topics=["work"])

    body = client.get("/api/v1/scenarios/restaurant/vocabulary", headers=headers).json()

    assert [w["term"] for w in body["related"]] == ["mesero"]


def test_a_word_is_never_both_on_topic_and_related(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "camarero", topics=["restaurant"], synonyms=["mesero"])
    _word(client, headers, group_id, "mesero", topics=["restaurant"])

    body = client.get("/api/v1/scenarios/restaurant/vocabulary", headers=headers).json()

    on_topic = {w["id"] for w in body["on_topic"]}
    related = {w["id"] for w in body["related"]}
    assert on_topic & related == set()


def test_another_accounts_words_are_never_suggested(client, auth_headers):
    alex = auth_headers()
    group_id = _group(client, alex)
    _word(client, alex, group_id, "camarero", topics=["restaurant"])

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get("/api/v1/scenarios/restaurant/vocabulary", headers=sam).json()["on_topic"] == []


def test_vocabulary_for_an_unknown_scenario_is_a_404(client, headers):
    assert client.get("/api/v1/scenarios/nonsense/vocabulary", headers=headers).status_code == 404


def test_scenario_vocabulary_requires_authentication(client):
    assert client.get("/api/v1/scenarios/restaurant/vocabulary").status_code == 401
