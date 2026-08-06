"""Backend-selected multiple-choice distractors on GET /review/sessions
(issue #205 TODOs 0, 1, 5, 8 — the safely shippable half; TODO 2's FSRS
isolation is deliberately not wired to this endpoint yet, see the issue).
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


def _group(client, headers) -> int:
    return client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()["id"]


def _word(client, headers, group_id: int, term: str, translation: str) -> int:
    return client.post(
        f"/api/v1/groups/{group_id}/words",
        json={"term": term, "target_language": "Spanish", "translations": [translation]},
        headers=headers,
    ).json()["id"]


def _enable_semantic_relatedness(client, headers):
    resp = client.put(
        "/api/v1/recall-settings", json={"semantic_relatedness_enabled": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text


def test_mcq_options_are_absent_with_the_flag_off(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "hola", "hello")
    _word(client, headers, group_id, "adios", "goodbye")

    resp = client.post("/api/v1/review/sessions", json={"mode": "walking"}, headers=headers)

    assert resp.status_code == 201, resp.text
    assert all(w["mcq_options"] is None for w in resp.json()["words"])


def test_mcq_options_are_absent_in_a_typed_answer_mode_even_with_the_flag_on(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "hola", "hello")
    _enable_semantic_relatedness(client, headers)

    resp = client.post("/api/v1/review/sessions", json={"mode": "standard"}, headers=headers)

    assert resp.status_code == 201, resp.text
    assert all(w["mcq_options"] is None for w in resp.json()["words"])


def test_mcq_options_are_present_in_a_multiple_choice_mode_with_the_flag_on(client, headers):
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "hola", "hello")
    for i in range(4):
        _word(client, headers, group_id, f"word{i}", f"translation{i}")
    _enable_semantic_relatedness(client, headers)

    resp = client.post("/api/v1/review/sessions", json={"mode": "walking"}, headers=headers)

    assert resp.status_code == 201, resp.text
    target = next(w for w in resp.json()["words"] if w["id"] == word_id)
    assert target["mcq_options"] is not None
    assert "hello" in target["mcq_options"]
    assert len(target["mcq_options"]) == len(set(target["mcq_options"]))  # no duplicate options


def test_a_thin_vocabulary_never_falls_back_to_the_literal_none_of_the_above_string(client, headers):
    """TODO 5: the historical defect this replaces. A break/night session
    used to draw distractors only from its own tiny loaded queue; the
    backend selector draws from the whole account instead."""
    group_id = _group(client, headers)
    _word(client, headers, group_id, "hola", "hello")
    _enable_semantic_relatedness(client, headers)

    resp = client.post("/api/v1/review/sessions", json={"mode": "break", "limit": 2}, headers=headers)

    assert resp.status_code == 201, resp.text
    for word in resp.json()["words"]:
        assert word["mcq_options"] is None or "None of the above" not in word["mcq_options"]


def test_mistakes_mode_never_receives_mcq_options(client, headers):
    """MULTIPLE_CHOICE_MODES is exactly {walking, night, break} — mistakes
    stays a typed-answer mode regardless of the flag."""
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "hola", "hello")
    session_id = client.post("/api/v1/review/sessions", json={"mode": "standard"}, headers=headers).json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word_id, "outcome": "incorrect", "attempted_answer": "wrong"},
        headers=headers,
    )
    _enable_semantic_relatedness(client, headers)

    resp = client.post("/api/v1/review/sessions", json={"mode": "mistakes"}, headers=headers)

    assert resp.status_code == 201, resp.text
    assert all(w["mcq_options"] is None for w in resp.json()["words"])
