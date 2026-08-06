"""Learning path generation and progress over HTTP (issue #137).

Generation always answers 200 with a `status`, so most of these check that the
three states stay distinguishable — and that a model's plan is bounded before
anything is stored.
"""
from __future__ import annotations

import pytest

from app.domain.exceptions import AIProviderUnavailableError


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


class _Planner:
    """Returns a fixed plan, or raises."""

    name = "ollama"
    model = "llama3.2"

    def __init__(self, plan=None, error: Exception | None = None):
        self.plan = plan
        self.error = error
        self.calls = 0

    async def generate_learning_path(self, goal, target_language, max_milestones, min_milestones):
        self.calls += 1
        if self.error:
            raise self.error
        return self.plan


class _use:
    """Override just the AI provider, for the duration of a block.

    Only this one key is removed afterwards. `dependency_overrides.clear()`
    would also drop the test database override the client fixture installs,
    and every request after it would fail authentication for reasons that look
    nothing like the cause.
    """

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


def _generate(client, headers, goal="Order food in Spain"):
    return client.post(
        "/api/v1/learning-paths/generate",
        json={"goal": goal, "target_language": "Spanish"},
        headers=headers,
    )


GOOD_PLAN = [
    {"title": "Greetings", "topic": "greetings", "target_word_count": 5, "description": "Say hello"},
    {"title": "Ordering", "topic": "restaurant", "target_word_count": 8, "cefr_level": "A2"},
]


def _group(client, headers) -> int:
    return client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    ).json()["id"]


def _word(client, headers, group_id: int, term: str, topics: list[str]):
    word_id = client.post(
        f"/api/v1/groups/{group_id}/words",
        json={"term": term, "target_language": "Spanish", "translations": ["x"]},
        headers=headers,
    ).json()["id"]
    client.patch(
        f"/api/v1/words/{word_id}/associations",
        json={"add": [{"kind": "topic", "value": t} for t in topics], "remove": []},
        headers=headers,
    )
    return word_id


# --- The three states -------------------------------------------------------


def test_a_goal_becomes_a_path(client, headers):
    with _use(_Planner(plan=GOOD_PLAN)):
        resp = _generate(client, headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert [m["title"] for m in body["path"]["milestones"]] == ["Greetings", "Ordering"]


def test_no_provider_reports_disabled_rather_than_failing(client, headers):
    """A provider switched off is a normal state of a healthy install."""
    with _use(None):
        resp = _generate(client, headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"
    assert resp.json()["path"] is None


def test_an_unreachable_model_reports_unavailable(client, headers):
    with _use(_Planner(error=AIProviderUnavailableError("model is starting"))):
        resp = _generate(client, headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "unavailable"


def test_generation_requires_authentication(client):
    resp = client.post(
        "/api/v1/learning-paths/generate", json={"goal": "x", "target_language": "Spanish"}
    )
    assert resp.status_code == 401


# --- The plan is bounded before anything is stored -------------------------


def test_an_over_long_plan_is_truncated_before_storage(client, headers):
    plan = [
        {"title": f"Step {i}", "topic": f"t{i}", "target_word_count": 5} for i in range(40)
    ]
    with _use(_Planner(plan=plan)):
        body = _generate(client, headers).json()

    assert len(body["path"]["milestones"]) <= 8


def test_an_unusable_plan_is_reported_rather_than_stored(client, headers):
    """An empty path presented as a plan is worse than an error — the learner
    cannot tell whether it means "no steps needed" or "this went wrong"."""
    with _use(_Planner(plan=[{"title": "", "topic": ""}])):
        resp = _generate(client, headers)

    assert resp.json()["status"] == "unavailable"
    assert client.get("/api/v1/learning-paths", headers=headers).json() == []


def test_an_absurd_word_target_is_capped_in_the_stored_path(client, headers):
    plan = [
        {"title": "A", "topic": "a", "target_word_count": 99999},
        {"title": "B", "topic": "b", "target_word_count": 5},
    ]
    with _use(_Planner(plan=plan)):
        body = _generate(client, headers).json()

    assert body["path"]["milestones"][0]["target_word_count"] <= 60


def test_an_empty_goal_is_rejected_before_the_model_is_called(client, headers):
    planner = _Planner(plan=GOOD_PLAN)
    with _use(planner):
        resp = client.post(
            "/api/v1/learning-paths/generate",
            json={"goal": "   ", "target_language": "Spanish"},
            headers=headers,
        )

    assert resp.status_code == 422
    assert planner.calls == 0


# --- Progress is measured, not stored --------------------------------------


def test_progress_reflects_the_learners_actual_vocabulary(client, headers):
    """A stored percentage is a number that was true once."""
    with _use(_Planner(plan=GOOD_PLAN)):
        path_id = _generate(client, headers).json()["path"]["id"]

    group_id = _group(client, headers)
    for index in range(5):
        _word(client, headers, group_id, f"hola{index}", ["greetings"])

    body = client.get(f"/api/v1/learning-paths/{path_id}", headers=headers).json()

    assert body["milestones"][0]["words_held"] == 5
    assert body["milestones"][0]["complete"] is True
    assert body["completed_count"] == 1


def test_deleting_words_moves_progress_back(client, headers):
    """The case a stored percentage gets wrong."""
    with _use(_Planner(plan=GOOD_PLAN)):
        path_id = _generate(client, headers).json()["path"]["id"]

    group_id = _group(client, headers)
    word_ids = [_word(client, headers, group_id, f"hola{i}", ["greetings"]) for i in range(5)]
    assert client.get(f"/api/v1/learning-paths/{path_id}", headers=headers).json()["completed_count"] == 1

    client.delete(f"/api/v1/words/{word_ids[0]}", headers=headers)

    body = client.get(f"/api/v1/learning-paths/{path_id}", headers=headers).json()
    assert body["milestones"][0]["complete"] is False
    assert body["completed_count"] == 0


def test_the_next_milestone_is_the_first_unfinished_one(client, headers):
    with _use(_Planner(plan=GOOD_PLAN)):
        path_id = _generate(client, headers).json()["path"]["id"]

    group_id = _group(client, headers)
    for index in range(5):
        _word(client, headers, group_id, f"hola{index}", ["greetings"])

    body = client.get(f"/api/v1/learning-paths/{path_id}", headers=headers).json()

    assert body["next_milestone"]["title"] == "Ordering"


def test_a_fresh_path_reports_no_progress(client, headers):
    with _use(_Planner(plan=GOOD_PLAN)):
        body = _generate(client, headers).json()

    assert body["path"]["share"] == 0.0
    assert body["path"]["next_milestone"]["title"] == "Greetings"


# --- Ownership --------------------------------------------------------------


def test_another_accounts_path_is_a_404_not_a_403(client, auth_headers):
    """A goal is a personal thing to leak the existence of."""
    alex = auth_headers()
    with _use(_Planner(plan=GOOD_PLAN)):
        path_id = _generate(client, alex).json()["path"]["id"]

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get(f"/api/v1/learning-paths/{path_id}", headers=sam).status_code == 404
    assert client.delete(f"/api/v1/learning-paths/{path_id}", headers=sam).status_code == 404


def test_paths_are_listed_per_account(client, auth_headers):
    alex = auth_headers()
    with _use(_Planner(plan=GOOD_PLAN)):
        _generate(client, alex)

    sam = auth_headers(username="sam", email="sam@example.com")

    assert len(client.get("/api/v1/learning-paths", headers=alex).json()) == 1
    assert client.get("/api/v1/learning-paths", headers=sam).json() == []


def test_a_path_can_be_deleted(client, headers):
    with _use(_Planner(plan=GOOD_PLAN)):
        path_id = _generate(client, headers).json()["path"]["id"]

    assert client.delete(f"/api/v1/learning-paths/{path_id}", headers=headers).status_code == 204
    assert client.get("/api/v1/learning-paths", headers=headers).json() == []
