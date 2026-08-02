"""Graph search and CEFR progress over HTTP (issue #143).

The derivation is tested in `test_knowledge_graph.py` and
`test_cefr_progress.py`. What is checked here is what the endpoints are
*allowed to say* — including that they refuse to name an overall level, and
that one account's graph never reaches into another's.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


def _group(client, headers) -> int:
    resp = client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _word(
    client,
    headers,
    group_id: int,
    term: str,
    *,
    cefr_level: str | None = None,
    synonyms: list[str] | None = None,
    topics: list[str] | None = None,
) -> int:
    payload = {"term": term, "target_language": "Spanish", "translations": ["x"]}
    if cefr_level:
        payload["cefr_level"] = cefr_level
    resp = client.post(f"/api/v1/groups/{group_id}/words", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    word_id = resp.json()["id"]

    # Associations are a separate endpoint, not fields on create.
    add = [{"kind": "synonym", "value": v} for v in (synonyms or [])]
    add += [{"kind": "topic", "value": v} for v in (topics or [])]
    if add:
        resp = client.patch(
            f"/api/v1/words/{word_id}/associations",
            json={"add": add, "remove": []},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
    return word_id


# --- "What should I learn before this word?" -------------------------------


def test_an_easier_related_word_is_a_prerequisite(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="A1", topics=["home"])
    hard = _word(client, headers, group_id, "vivienda", cefr_level="B2", topics=["home"])

    body = client.get(f"/api/v1/words/{hard}/prerequisites", headers=headers).json()

    assert [p["term"] for p in body["prerequisites"]] == ["casa"]


def test_a_word_at_the_same_level_is_not_a_prerequisite(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="B2", topics=["home"])
    other = _word(client, headers, group_id, "vivienda", cefr_level="B2", topics=["home"])

    body = client.get(f"/api/v1/words/{other}/prerequisites", headers=headers).json()

    assert body["prerequisites"] == []


def test_a_word_with_no_level_says_so_rather_than_answering_with_a_guess(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="A1", topics=["home"])
    unknown = _word(client, headers, group_id, "vivienda", topics=["home"])

    body = client.get(f"/api/v1/words/{unknown}/prerequisites", headers=headers).json()

    assert body["level_unknown"] is True
    assert body["prerequisites"] == []


def test_a_prerequisite_says_why_it_is_one(client, headers):
    """A graph that cannot justify an edge is one nobody trusts enough to act
    on."""
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="A1", synonyms=["vivienda"])
    hard = _word(client, headers, group_id, "vivienda", cefr_level="B2")

    body = client.get(f"/api/v1/words/{hard}/prerequisites", headers=headers).json()

    assert body["prerequisites"][0]["evidence"]
    assert body["prerequisites"][0]["relation"] == "synonym"


def test_a_word_is_never_listed_as_its_own_prerequisite(client, headers):
    group_id = _group(client, headers)
    word_id = _word(client, headers, group_id, "casa", cefr_level="B1", synonyms=["casa"])

    body = client.get(f"/api/v1/words/{word_id}/prerequisites", headers=headers).json()

    assert body["prerequisites"] == []


def test_asking_about_another_accounts_word_is_a_404_not_a_403(client, auth_headers):
    """A distinguishable 403 would confirm that someone else's word exists to
    anyone willing to enumerate ids."""
    alex = auth_headers()
    group_id = _group(client, alex)
    word_id = _word(client, alex, group_id, "casa", cefr_level="A1")

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get(f"/api/v1/words/{word_id}/prerequisites", headers=sam).status_code == 404


def test_an_unknown_word_is_a_404(client, headers):
    assert client.get("/api/v1/words/999999/prerequisites", headers=headers).status_code == 404


# --- Related words ---------------------------------------------------------


def test_related_words_are_returned_strongest_first(client, headers):
    group_id = _group(client, headers)
    target = _word(client, headers, group_id, "gato", synonyms=["minino"], topics=["animals"])
    _word(client, headers, group_id, "minino", topics=["animals"])
    _word(client, headers, group_id, "perro", topics=["animals"])

    body = client.get(f"/api/v1/words/{target}/related", headers=headers).json()

    assert body[0]["relation"] == "synonym"
    assert {r["term"] for r in body} == {"minino", "perro"}


def test_a_word_the_learner_does_not_have_produces_no_edge(client, headers):
    """An edge to a word they do not study would be an edge to nothing."""
    group_id = _group(client, headers)
    target = _word(client, headers, group_id, "gato", synonyms=["quetzalcoatl"])

    assert client.get(f"/api/v1/words/{target}/related", headers=headers).json() == []


def test_words_from_another_account_never_appear_in_the_graph(client, auth_headers):
    alex = auth_headers()
    alex_group = _group(client, alex)
    _word(client, alex, alex_group, "minino", topics=["animals"])

    sam = auth_headers(username="sam", email="sam@example.com")
    sam_group = _group(client, sam)
    sam_word = _word(client, sam, sam_group, "gato", synonyms=["minino"], topics=["animals"])

    assert client.get(f"/api/v1/words/{sam_word}/related", headers=sam).json() == []


def test_confusions_from_the_mistake_log_become_edges(client, headers):
    """The payoff of #134 meeting #138: the one relation derived from observed
    behaviour rather than a label someone typed."""
    group_id = _group(client, headers)
    gato = _word(client, headers, group_id, "gato")
    _word(client, headers, group_id, "gata")

    session = client.post(
        "/api/v1/review/sessions", json={"mode": "standard", "group_id": group_id}, headers=headers
    ).json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session}/answers",
        json={"word_id": gato, "outcome": "incorrect", "attempted_answer": "gata"},
        headers=headers,
    )

    body = client.get(f"/api/v1/words/{gato}/related", headers=headers).json()

    assert [r["relation"] for r in body] == ["confused_with"]
    assert body[0]["term"] == "gata"


# --- CEFR progress ---------------------------------------------------------


def test_every_level_is_reported_even_when_empty(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="A1")

    body = client.get("/api/v1/me/cefr-progress", headers=headers).json()

    assert [level["level"] for level in body["levels"]] == ["A1", "A2", "B1", "B2", "C1", "C2"]


def test_words_with_no_level_are_reported_separately(client, headers):
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="A1")
    _word(client, headers, group_id, "mesa")

    body = client.get("/api/v1/me/cefr-progress", headers=headers).json()

    assert body["unlevelled"]["total"] == 1
    assert body["total_words"] == 2


def test_the_response_never_names_an_overall_level(client, headers):
    """The number everyone wants and the one this data cannot support. Someone
    who added forty C1 words yesterday is not C1."""
    group_id = _group(client, headers)
    _word(client, headers, group_id, "casa", cefr_level="C1")

    body = client.get("/api/v1/me/cefr-progress", headers=headers).json()

    assert "level" not in body
    assert "current_level" not in body
    assert "overall_level" not in body


def test_an_empty_deck_reports_zeroes_rather_than_failing(client, headers):
    body = client.get("/api/v1/me/cefr-progress", headers=headers).json()

    assert body["total_words"] == 0
    assert all(level["total"] == 0 for level in body["levels"])
    assert body["unlevelled"] is None


def test_progress_covers_every_group_not_just_one(client, headers):
    """A vocabulary split across groups is still one vocabulary."""
    first = _group(client, headers)
    second = client.post(
        "/api/v1/groups", json={"name": "Travel", "target_language": "Spanish"}, headers=headers
    ).json()["id"]
    _word(client, headers, first, "casa", cefr_level="A1")
    _word(client, headers, second, "avión", cefr_level="A1")

    body = client.get("/api/v1/me/cefr-progress", headers=headers).json()

    assert next(level for level in body["levels"] if level["level"] == "A1")["total"] == 2


def test_another_accounts_words_are_not_counted(client, auth_headers):
    alex = auth_headers()
    group_id = _group(client, alex)
    _word(client, alex, group_id, "casa", cefr_level="A1")

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get("/api/v1/me/cefr-progress", headers=sam).json()["total_words"] == 0


def test_cefr_progress_requires_authentication(client):
    assert client.get("/api/v1/me/cefr-progress").status_code == 401
