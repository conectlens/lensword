"""Account-wide `/me/diagnoses` and `/me/interventions` (issue #192).

Both used to be permanent MCP-side stubs
(`{"items": [], "available": False}`) because no backend endpoint existed
to list either collection across a whole account rather than one word.
This covers the endpoints themselves: real data, pagination that actually
advances, and tenant isolation — the same shape
`test_diagnosis_persistence_api.py` and `test_intervention_persistence.py`
already use for the per-word equivalents.
"""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import Diagnosis, DiagnosisEvidence, InterventionPlan
from app.infrastructure.repositories import (
    SqlAlchemyDiagnosisRepository,
    SqlAlchemyInterventionRepository,
    SqlAlchemyUserRepository,
)

NOW = datetime(2026, 8, 6, 9, 0)


def _setup_group_with_word(client, headers, term="Hola", translation="Hello"):
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": "Spanish", "translations": [translation]},
        headers=headers,
    ).json()
    return group, word


def _diagnosis(word_id: int, user_id: int, outcome: str = "exact_confusion", **overrides) -> Diagnosis:
    defaults = dict(
        word_id=word_id,
        user_id=user_id,
        outcome=outcome,
        evidence=(DiagnosisEvidence(kind="k", observation_ids=("o-1",), weight=0.6, description="d"),),
        confidence=0.6,
        rules_version=1,
        diagnosed_at=NOW,
    )
    defaults.update(overrides)
    return Diagnosis(**defaults)


def _plan(word_id: int, user_id: int, strategy: str = "contrast", **overrides) -> InterventionPlan:
    defaults = dict(
        word_id=word_id, user_id=user_id, diagnosis_outcome="exact_confusion", strategy=strategy,
        policy_version=1, eligible=True, rationale="r", planned_at=NOW,
    )
    defaults.update(overrides)
    return InterventionPlan(**defaults)


# --- /me/diagnoses -----------------------------------------------------


def test_list_my_diagnoses_spans_every_word_not_one(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word_a = _setup_group_with_word(client, headers, term="uno", translation="one")
    _group, word_b = _setup_group_with_word(client, headers, term="dos", translation="two")
    repo = SqlAlchemyDiagnosisRepository(db_session)
    repo.add(_diagnosis(word_a["id"], owner_id, outcome="forgetting", diagnosed_at=datetime(2026, 8, 1, 9, 0)))
    repo.add(_diagnosis(word_b["id"], owner_id, outcome="exact_confusion", diagnosed_at=datetime(2026, 8, 2, 9, 0)))

    resp = client.get("/api/v1/me/diagnoses", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert {item["word_id"] for item in body["items"]} == {word_a["id"], word_b["id"]}
    # Newest first.
    assert body["items"][0]["outcome"] == "exact_confusion"
    assert body["next_cursor"] is None


def test_list_my_diagnoses_paginates_with_a_real_cursor(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyDiagnosisRepository(db_session)
    for i in range(3):
        repo.add(_diagnosis(word["id"], owner_id, diagnosed_at=datetime(2026, 8, 1 + i, 9, 0)))

    first = client.get("/api/v1/me/diagnoses?limit=2", headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second = client.get(f"/api/v1/me/diagnoses?limit=2&cursor={first_body['next_cursor']}", headers=headers)
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None


def test_list_my_diagnoses_never_returns_another_accounts_rows(client, auth_headers, db_session):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("owner@example.com").id
    _group, word = _setup_group_with_word(client, owner_headers)
    SqlAlchemyDiagnosisRepository(db_session).add(_diagnosis(word["id"], owner_id))

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    resp = client.get("/api/v1/me/diagnoses", headers=stranger_headers)

    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_list_my_diagnoses_requires_authentication(client):
    resp = client.get("/api/v1/me/diagnoses")
    assert resp.status_code in (401, 403)


# --- /me/interventions ---------------------------------------------------


def test_list_my_interventions_spans_every_word_not_one(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word_a = _setup_group_with_word(client, headers, term="uno", translation="one")
    _group, word_b = _setup_group_with_word(client, headers, term="dos", translation="two")
    repo = SqlAlchemyInterventionRepository(db_session)
    repo.add_plan(_plan(word_a["id"], owner_id, strategy="isolate", planned_at=datetime(2026, 8, 1, 9, 0)))
    repo.add_plan(_plan(word_b["id"], owner_id, strategy="contrast", planned_at=datetime(2026, 8, 2, 9, 0)))

    resp = client.get("/api/v1/me/interventions", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert {item["word_id"] for item in body["items"]} == {word_a["id"], word_b["id"]}
    assert body["items"][0]["strategy"] == "contrast"  # newest first
    assert body["next_cursor"] is None


def test_list_my_interventions_paginates_with_a_real_cursor(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyInterventionRepository(db_session)
    for i in range(3):
        repo.add_plan(_plan(word["id"], owner_id, planned_at=datetime(2026, 8, 1 + i, 9, 0)))

    first = client.get("/api/v1/me/interventions?limit=2", headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second = client.get(f"/api/v1/me/interventions?limit=2&cursor={first_body['next_cursor']}", headers=headers)
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None


def test_list_my_interventions_never_returns_another_accounts_rows(client, auth_headers, db_session):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("owner@example.com").id
    _group, word = _setup_group_with_word(client, owner_headers)
    SqlAlchemyInterventionRepository(db_session).add_plan(_plan(word["id"], owner_id))

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    resp = client.get("/api/v1/me/interventions", headers=stranger_headers)

    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_list_my_interventions_requires_authentication(client):
    resp = client.get("/api/v1/me/interventions")
    assert resp.status_code in (401, 403)
