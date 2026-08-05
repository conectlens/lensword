"""The conversation tutor over HTTP (issue #135).

The claim tested hardest is the one that decides whether a chat feels broken:
the learner's own turn is stored *before* the model is called, so a model being
down never costs them what they typed.
"""
from __future__ import annotations

import pytest

from app.domain.exceptions import AIProviderUnavailableError


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


class _Tutor:
    """Answers with a fixed payload, or raises."""

    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload if payload is not None else {"reply": "¡Hola!"}
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
    also drop the database override the client fixture installs, and every
    request after it would fail authentication for reasons that look nothing
    like the cause.
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


def _start(client, headers, **over) -> int:
    body = {"target_language": "Spanish", "difficulty": "steady", **over}
    resp = client.post("/api/v1/conversations", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _say(client, headers, session_id: int, text: str):
    return client.post(
        f"/api/v1/conversations/{session_id}/message", json={"text": text}, headers=headers
    )


# --- Starting ---------------------------------------------------------------


def test_a_conversation_starts_empty(client, headers):
    session_id = _start(client, headers)

    body = client.get(f"/api/v1/conversations/{session_id}", headers=headers).json()
    assert body["messages"] == []
    assert body["ended_at"] is None


def test_starting_requires_authentication(client):
    assert client.post("/api/v1/conversations", json={"target_language": "Spanish"}).status_code == 401


# --- The learner's turn survives a broken model ----------------------------


def test_the_learner_turn_is_kept_when_the_model_is_down(client, headers):
    """Losing what someone typed because a model was down is the one outcome
    that makes a chat feel broken, and it is entirely avoidable."""
    session_id = _start(client, headers)

    with _use(_Tutor(error=AIProviderUnavailableError("model is starting"))):
        resp = _say(client, headers, session_id, "hola, yo tiene un gato")

    assert resp.status_code == 200
    assert resp.json()["status"] == "unavailable"
    assert resp.json()["learner_message"]["text"] == "hola, yo tiene un gato"

    stored = client.get(f"/api/v1/conversations/{session_id}", headers=headers).json()
    assert [m["text"] for m in stored["messages"]] == ["hola, yo tiene un gato"]


def test_the_learner_turn_is_kept_when_ai_is_switched_off(client, headers):
    session_id = _start(client, headers)

    with _use(None):
        resp = _say(client, headers, session_id, "hola")

    assert resp.json()["status"] == "disabled"
    assert resp.json()["learner_message"]["text"] == "hola"


def test_a_nonsense_reply_is_reported_without_losing_the_turn(client, headers):
    session_id = _start(client, headers)

    with _use(_Tutor(payload={"reply": "   "})):
        resp = _say(client, headers, session_id, "hola")

    assert resp.json()["status"] == "unavailable"
    assert resp.json()["learner_message"] is not None


# --- A normal exchange ------------------------------------------------------


def test_a_reply_is_stored_alongside_the_learner_turn(client, headers):
    session_id = _start(client, headers)

    with _use(_Tutor(payload={"reply": "¡Claro! ¿Cómo estás?"})):
        resp = _say(client, headers, session_id, "hola")

    assert resp.json()["status"] == "ok"
    stored = client.get(f"/api/v1/conversations/{session_id}", headers=headers).json()
    assert [m["speaker"] for m in stored["messages"]] == ["learner", "tutor"]


def test_a_correction_quoting_the_learner_is_kept(client, headers):
    session_id = _start(client, headers)
    payload = {
        "reply": "Casi.",
        "corrections": [
            {"original": "yo tiene", "corrected": "yo tengo", "explanation": "first person"}
        ],
    }

    with _use(_Tutor(payload=payload)):
        resp = _say(client, headers, session_id, "yo tiene un gato")

    corrections = resp.json()["tutor_message"]["corrections"]
    assert corrections[0]["corrected"] == "yo tengo"


def test_a_correction_quoting_words_nobody_typed_is_dropped(client, headers):
    """A highlight pointing at text the learner never wrote teaches them to
    ignore highlights entirely."""
    session_id = _start(client, headers)
    payload = {
        "reply": "Bien.",
        "corrections": [{"original": "el perro", "corrected": "la perra", "explanation": ""}],
    }

    with _use(_Tutor(payload=payload)):
        resp = _say(client, headers, session_id, "yo tengo un gato")

    assert resp.json()["tutor_message"]["corrections"] == []


def test_corrections_are_capped_per_turn(client, headers):
    """Correcting everything turns a conversation into a test."""
    session_id = _start(client, headers)
    said = "a b c d e f"
    payload = {
        "reply": "Vale.",
        "corrections": [
            {"original": letter, "corrected": letter.upper() + "!", "explanation": ""}
            for letter in "abcdef"
        ],
    }

    with _use(_Tutor(payload=payload)):
        resp = _say(client, headers, session_id, said)

    assert len(resp.json()["tutor_message"]["corrections"]) <= 3


# --- What the tutor is told -------------------------------------------------


def test_the_learners_own_vocabulary_is_offered_to_the_tutor(client, headers):
    group_id = client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    ).json()["id"]
    client.post(
        f"/api/v1/groups/{group_id}/words",
        json={"term": "murciélago", "target_language": "Spanish", "translations": ["bat"]},
        headers=headers,
    )
    session_id = _start(client, headers)

    tutor = _Tutor()
    with _use(tutor):
        _say(client, headers, session_id, "hola")

    assert "murciélago" in tutor.last_context.vocabulary


def test_prior_turns_reach_the_tutor_but_the_new_one_is_not_duplicated(client, headers):
    """The new message is passed separately, so including it in history too
    would show the tutor the same sentence twice."""
    session_id = _start(client, headers)
    tutor = _Tutor()

    with _use(tutor):
        _say(client, headers, session_id, "primero")
        _say(client, headers, session_id, "segundo")

    texts = [turn.text for turn in tutor.last_context.history]
    assert "primero" in texts
    assert texts.count("segundo") == 0


def test_the_chosen_difficulty_reaches_the_tutor(client, headers):
    session_id = _start(client, headers, difficulty="stretch")
    tutor = _Tutor()

    with _use(tutor):
        _say(client, headers, session_id, "hola")

    assert tutor.last_context.difficulty.value == "stretch"


# --- Lifecycle and ownership ------------------------------------------------


def test_a_conversation_can_be_ended(client, headers):
    session_id = _start(client, headers)

    resp = client.post(f"/api/v1/conversations/{session_id}/end", headers=headers)

    assert resp.json()["ended_at"] is not None


def test_another_accounts_conversation_is_a_404_not_a_403(client, auth_headers):
    """A conversation is the most personal thing this product stores."""
    alex = auth_headers()
    session_id = _start(client, alex)

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get(f"/api/v1/conversations/{session_id}", headers=sam).status_code == 404
    assert _say(client, sam, session_id, "hola").status_code == 404
    assert client.delete(f"/api/v1/conversations/{session_id}", headers=sam).status_code == 404


def test_conversations_are_listed_per_account(client, auth_headers):
    alex = auth_headers()
    _start(client, alex)
    sam = auth_headers(username="sam", email="sam@example.com")

    assert len(client.get("/api/v1/conversations", headers=alex).json()) == 1
    assert client.get("/api/v1/conversations", headers=sam).json() == []


def test_deleting_a_conversation_takes_its_messages(client, headers):
    session_id = _start(client, headers)
    with _use(_Tutor()):
        _say(client, headers, session_id, "hola")

    assert client.delete(f"/api/v1/conversations/{session_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/conversations/{session_id}", headers=headers).status_code == 404


def test_an_empty_message_is_rejected(client, headers):
    session_id = _start(client, headers)

    assert _say(client, headers, session_id, "").status_code == 422
