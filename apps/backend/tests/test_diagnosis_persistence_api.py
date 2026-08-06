"""Persisted diagnoses and their API surface (#180, issue #183 TODO 5).

Covers the issue's verify step for this layer: "all endpoints pass tenant
isolation, malformed input, deleted-word, and stale-ruleset tests." The
pure rules engine itself is covered in test_diagnosis_engine.py — this
file is about the repository and the two read endpoints that sit on top
of it, and about `SubmitAnswerUseCase` actually producing a `Diagnosis`
row end to end when `learning_diagnosis_enabled` is on (mirroring the
same pattern test_learning_observations.py and test_knowledge_edges.py
already use for their own flags).
"""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import Diagnosis, DiagnosisEvidence
from app.infrastructure.repositories import (
    SqlAlchemyDiagnosisRepository,
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


def _enable_diagnosis(client, headers):
    resp = client.put("/api/v1/recall-settings", json={"learning_diagnosis_enabled": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["learning_diagnosis_enabled"] is True


def _answer(client, headers, word, outcome="incorrect", **fields):
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    return client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": outcome, **fields},
        headers=headers,
    )


def _diagnosis(word_id: int, user_id: int, outcome: str = "exact_confusion", **overrides) -> Diagnosis:
    defaults = dict(
        word_id=word_id,
        user_id=user_id,
        outcome=outcome,
        evidence=(
            DiagnosisEvidence(kind="k", observation_ids=("o-1",), weight=0.6, description="d"),
        ),
        confidence=0.6,
        rules_version=1,
        diagnosed_at=NOW,
    )
    defaults.update(overrides)
    return Diagnosis(**defaults)


# --- Repository ---


def test_add_and_latest_for_word_round_trip(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyDiagnosisRepository(db_session)

    repo.add(_diagnosis(word["id"], owner_id))
    latest = repo.latest_for_word(owner_id, word["id"])

    assert latest is not None
    assert latest.outcome == "exact_confusion"
    assert latest.evidence[0].kind == "k"
    assert latest.confidence == 0.6


def test_latest_for_word_returns_none_when_nothing_diagnosed(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyDiagnosisRepository(db_session)

    assert repo.latest_for_word(owner_id, word["id"]) is None


def test_list_for_word_is_append_only_newest_first(db_session, client, auth_headers):
    """Corrections are new rows, never rewrites — matching the
    mistake_events / learning_observations evidence-table pattern."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyDiagnosisRepository(db_session)

    repo.add(_diagnosis(word["id"], owner_id, outcome="forgetting", diagnosed_at=datetime(2026, 8, 5, 9, 0)))
    repo.add(_diagnosis(word["id"], owner_id, outcome="exact_confusion", diagnosed_at=datetime(2026, 8, 6, 9, 0)))

    history = repo.list_for_word(owner_id, word["id"])
    assert len(history) == 2
    assert [d.outcome for d in history] == ["exact_confusion", "forgetting"]
    assert repo.latest_for_word(owner_id, word["id"]).outcome == "exact_confusion"


def test_list_for_word_respects_limit(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyDiagnosisRepository(db_session)

    for i in range(5):
        repo.add(_diagnosis(word["id"], owner_id, diagnosed_at=datetime(2026, 8, 1 + i, 9, 0)))

    assert len(repo.list_for_word(owner_id, word["id"], limit=2)) == 2


# --- End-to-end: review submission produces a real diagnosis ---


def test_submitting_an_answer_persists_a_diagnosis_when_enabled(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers, term="palabra", translation="word")
    _enable_diagnosis(client, headers)

    resp = _answer(client, headers, word)
    assert resp.status_code == 200

    repo = SqlAlchemyDiagnosisRepository(db_session)
    latest = repo.latest_for_word(owner_id, word["id"])
    # A single incorrect answer with no prior recall and no other evidence
    # is genuinely insufficient — the engine abstaining is the correct,
    # conservative outcome, and abstentions are persisted rows too.
    assert latest is not None
    assert latest.is_abstention


def test_no_diagnosis_is_recorded_while_diagnosis_is_disabled(client, auth_headers, db_session):
    """ADR 0007: with the flag off, the request path never reaches the
    diagnoses table at all, matching the same guarantee already covered
    for learning_observations and knowledge_edges."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    # Diagnosis left at its default (off).

    resp = _answer(client, headers, word)
    assert resp.status_code == 200

    repo = SqlAlchemyDiagnosisRepository(db_session)
    assert repo.latest_for_word(owner_id, word["id"]) is None


def test_a_real_exact_confusion_lands_in_the_diagnosis_endpoint(client, auth_headers, db_session):
    """End to end: a genuinely repeated confusion produces a real,
    non-abstention diagnosis, and the read endpoint surfaces it."""
    headers = auth_headers()
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    target = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "libre", "target_language": "Spanish", "translations": ["free"]},
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "libro", "target_language": "Spanish", "translations": ["book"]},
        headers=headers,
    )
    _enable_diagnosis(client, headers)

    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")

    resp = client.get(f"/api/v1/words/{target['id']}/diagnosis", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body is not None
    assert body["outcome"] == "exact_confusion"
    assert body["is_abstention"] is False
    assert body["confidence"] is not None

    history = client.get(f"/api/v1/words/{target['id']}/diagnosis/history", headers=headers).json()
    assert len(history) == 2  # one per answer submitted


# --- Endpoint: tenant isolation, malformed input, deleted word ---


def test_latest_diagnosis_endpoint_returns_null_for_a_word_with_none(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)

    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis", headers=headers)
    assert resp.status_code == 200
    assert resp.json() is None


def test_diagnosis_endpoints_404_for_a_nonexistent_word(client, auth_headers):
    headers = auth_headers()

    resp = client.get("/api/v1/words/999999/diagnosis", headers=headers)
    assert resp.status_code == 404

    resp = client.get("/api/v1/words/999999/diagnosis/history", headers=headers)
    assert resp.status_code == 404


def test_diagnosis_endpoints_404_for_another_users_word(client, auth_headers):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    _group, word = _setup_group_with_word(client, owner_headers)

    stranger_headers = auth_headers(username="stranger", email="stranger@example.com")
    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis", headers=stranger_headers)
    assert resp.status_code == 404

    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis/history", headers=stranger_headers)
    assert resp.status_code == 404


def test_diagnosis_endpoint_404s_after_the_word_is_deleted(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    SqlAlchemyDiagnosisRepository(db_session).add(_diagnosis(word["id"], owner_id))

    resp = client.delete(f"/api/v1/words/{word['id']}", headers=headers)
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis", headers=headers)
    assert resp.status_code == 404


def test_diagnosis_history_rejects_a_malformed_limit(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)

    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis/history?limit=not-a-number", headers=headers)
    assert resp.status_code == 422


def test_diagnosis_endpoint_requires_authentication(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)

    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis")
    assert resp.status_code in (401, 403)


def test_a_stale_ruleset_diagnosis_still_reads_back_correctly(db_session, client, auth_headers):
    """A diagnosis persisted under an older rules_version must still
    round-trip exactly as stored — the read path must not silently
    reinterpret or upgrade an old row to the current engine's semantics."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyDiagnosisRepository(db_session)

    repo.add(_diagnosis(word["id"], owner_id, outcome="forgetting", rules_version=0, confidence=0.4))

    resp = client.get(f"/api/v1/words/{word['id']}/diagnosis", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["rules_version"] == 0
    assert body["outcome"] == "forgetting"
    assert body["confidence"] == 0.4
