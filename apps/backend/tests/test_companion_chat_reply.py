"""The in-app companion chat exchange over HTTP (issue #343).

`POST /turns` records a turn some external companion already produced. An
in-app chat has no external author, so `POST /chat` owns both halves. The
claims tested hardest here are the two that decide whether a chat feels
broken: the user's turn survives a model that is down, and a retried send
does not duplicate the exchange.
"""
from __future__ import annotations

import pytest

from app.domain.exceptions import AIProviderUnavailableError


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


class _Companion:
    """Answers with a fixed payload, or raises."""

    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload if payload is not None else {"reply": "Claro, empecemos."}
        self.error = error
        self.calls = 0
        self.last_context = None

    async def converse(self, context, learner_message):
        self.calls += 1
        self.last_context = context
        if self.error:
            raise self.error
        return self.payload


class _use:
    """Override just the AI provider.

    Only this key is removed afterwards: `dependency_overrides.clear()` would
    also drop the database override the client fixture installs.
    """

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


def _enable(client, headers):
    response = client.put(
        "/api/v1/recall-settings",
        json={"ai_companion_enabled": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _start(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={
            "connection_id": "web-1",
            "client_id": "browser",
            "goal": "ordering coffee",
            "language": "Spanish",
            "difficulty": "steady",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _say(client, headers, session_id: str, content: str, operation_id: str | None = None):
    body: dict = {"content": content}
    if operation_id:
        body["operation_id"] = operation_id
    return client.post(
        f"/api/v1/companion/sessions/{session_id}/chat",
        json=body,
        headers=headers,
    )


def _turns(client, headers, session_id: str):
    response = client.get(f"/api/v1/companion/sessions/{session_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["turns"]


def test_reply_is_gated_by_the_companion_flag(client, auth_headers):
    """The chat surface must not be reachable when the feature is off."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    client.put("/api/v1/recall-settings", json={"ai_companion_enabled": False}, headers=headers)

    with _use(_Companion()):
        assert _say(client, headers, session["id"], "Hola").status_code == 403


def test_reply_records_both_halves_as_companion_turns(client, auth_headers):
    """The exchange lands in the durable session, not a parallel store."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    companion = _Companion({"reply": "Claro, empecemos."})
    with _use(companion):
        response = _say(client, headers, session["id"], "Quiero practicar")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["user_turn"]["role"] == "user"
    assert body["user_turn"]["content"] == "Quiero practicar"
    assert body["assistant_turn"]["role"] == "assistant"
    assert body["assistant_turn"]["content"] == "Claro, empecemos."

    # Readable through the ordinary session route, which is the whole point
    # of reusing companion turns rather than inventing a chat table.
    stored = _turns(client, headers, session["id"])
    assert [(t["role"], t["content"]) for t in stored] == [
        ("user", "Quiero practicar"),
        ("assistant", "Claro, empecemos."),
    ]


def test_a_model_that_is_down_still_keeps_what_the_user_typed(client, auth_headers):
    """The single outcome that makes a chat feel broken, and it is avoidable."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    with _use(_Companion(error=AIProviderUnavailableError("Ollama is unreachable"))):
        response = _say(client, headers, session["id"], "No me contestes")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["user_turn"]["content"] == "No me contestes"
    assert body["assistant_turn"] is None
    assert "unreachable" in body["detail"]

    assert [t["role"] for t in _turns(client, headers, session["id"])] == ["user"]


def test_no_provider_configured_reports_disabled_rather_than_failing(client, auth_headers):
    """A deployment with no AI configured is healthy, not erroring."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    with _use(None):
        response = _say(client, headers, session["id"], "Hola")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "disabled"
    assert body["user_turn"]["content"] == "Hola"
    assert body["assistant_turn"] is None


def test_a_retried_send_does_not_duplicate_the_exchange(client, auth_headers):
    """Same operation_id twice is one exchange and one model call."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    companion = _Companion({"reply": "Otra vez no."})
    with _use(companion):
        first = _say(client, headers, session["id"], "Hola", operation_id="op-1")
        second = _say(client, headers, session["id"], "Hola", operation_id="op-1")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["assistant_turn"]["id"] == second.json()["assistant_turn"]["id"]
    assert companion.calls == 1
    assert len(_turns(client, headers, session["id"])) == 2


def test_a_finished_session_cannot_be_replied_to(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    # Finished outside the provider override: finishing summarizes, and the
    # deterministic fallback is what an install with no AI configured uses.
    finished = client.post(f"/api/v1/companion/sessions/{session['id']}/finish", headers=headers)
    assert finished.status_code == 200, finished.text

    with _use(_Companion()):
        assert _say(client, headers, session["id"], "Hola").status_code == 409
