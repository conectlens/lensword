"""Learner-facing observation history and corrections (#180, issue #229 TODO 5).

Covers the issue's verify steps: a corrected observation is auditable (it
still appears in the private history view, with its correction attached)
and a diagnosis rebuild uses the correction — i.e. stops treating the
flagged observation as evidence — while the original row survives untouched.
"""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import LearningObservation, ObservationCorrection, ObservationCorrectionReason
from app.domain.value_objects import ReviewOutcome, SessionMode
from app.infrastructure.repositories import (
    SqlAlchemyLearningObservationRepository,
    SqlAlchemyUserRepository,
)


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


def _observation(user_id, word_id, observation_id, **overrides) -> LearningObservation:
    defaults = dict(
        observation_id=observation_id,
        word_id=word_id,
        user_id=user_id,
        outcome=ReviewOutcome.INCORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=datetime(2026, 8, 6, 9, 0),
        operation_id=observation_id,
    )
    defaults.update(overrides)
    return LearningObservation(**defaults)


# --- Repository ---


def test_add_correction_removes_the_observation_from_the_five_diagnosis_axes(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyLearningObservationRepository(db_session)
    _group, word = _setup_group_with_word(client, headers)

    repo.add(_observation(owner_id, word["id"], "obs-1", modality="typing", intervention_plan_ref="plan-1"))
    assert len(repo.list_for_word(owner_id, word["id"])) == 1
    assert len(repo.list_by_modality(owner_id, "typing")) == 1
    assert len(repo.list_by_intervention(owner_id, "plan-1")) == 1
    assert len(repo.list_in_window(owner_id, datetime(2026, 8, 5), datetime(2026, 8, 7))) == 1

    repo.add_correction(
        ObservationCorrection(
            correction_id="corr-1", observation_id="obs-1", user_id=owner_id,
            reason=ObservationCorrectionReason.MISGRADED, note=None, created_at=datetime(2026, 8, 6, 10, 0),
        )
    )

    assert repo.list_for_word(owner_id, word["id"]) == []
    assert repo.list_by_modality(owner_id, "typing") == []
    assert repo.list_by_intervention(owner_id, "plan-1") == []
    assert repo.list_in_window(owner_id, datetime(2026, 8, 5), datetime(2026, 8, 7)) == []


def test_list_for_user_still_shows_a_corrected_observation(client, auth_headers, db_session):
    """The auditable half: a diagnosis rebuild stops seeing this row, but
    the learner's own history view must not."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyLearningObservationRepository(db_session)
    _group, word = _setup_group_with_word(client, headers)
    repo.add(_observation(owner_id, word["id"], "obs-1"))

    repo.add_correction(
        ObservationCorrection(
            correction_id="corr-1", observation_id="obs-1", user_id=owner_id,
            reason=ObservationCorrectionReason.IRRELEVANT, note="not relevant", created_at=datetime(2026, 8, 6, 10, 0),
        )
    )

    history = repo.list_for_user(owner_id)
    assert [o.observation_id for o in history] == ["obs-1"]
    corrections = repo.corrections_for(owner_id, ["obs-1"])
    assert corrections["obs-1"].reason == ObservationCorrectionReason.IRRELEVANT
    assert corrections["obs-1"].note == "not relevant"


def test_list_for_user_paginates_newest_first(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyLearningObservationRepository(db_session)
    _group, word = _setup_group_with_word(client, headers)
    for i in range(5):
        repo.add(_observation(owner_id, word["id"], f"obs-{i}", observed_at=datetime(2026, 8, 1 + i, 9, 0)))

    page1 = repo.list_for_user(owner_id, limit=2, offset=0)
    page2 = repo.list_for_user(owner_id, limit=2, offset=2)
    assert [o.observation_id for o in page1] == ["obs-4", "obs-3"]
    assert [o.observation_id for o in page2] == ["obs-2", "obs-1"]


def test_correction_for_returns_none_when_unflagged(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyLearningObservationRepository(db_session)
    _group, word = _setup_group_with_word(client, headers)
    repo.add(_observation(owner_id, word["id"], "obs-1"))

    assert repo.correction_for(owner_id, "obs-1") is None


# --- API ---


def test_history_endpoint_returns_recorded_observations_newest_first(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)

    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=headers,
    )

    resp = client.get("/api/v1/me/observations", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["word_id"] == word["id"]
    assert body["items"][0]["word_term"] == "Hola"
    assert body["items"][0]["correction"] is None
    assert body["has_more"] is False


def test_history_endpoint_has_more_when_a_page_boundary_is_crossed(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    for _ in range(3):
        client.post(
            f"/api/v1/review/sessions/{session_id}/answers",
            json={"word_id": word["id"], "outcome": "incorrect"},
            headers=headers,
        )

    resp = client.get("/api/v1/me/observations", params={"limit": 2}, headers=headers)
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True


def test_correcting_an_observation_flags_it_and_it_still_appears_in_history(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=headers,
    )
    observation_id = client.get("/api/v1/me/observations", headers=headers).json()["items"][0]["observation_id"]

    resp = client.post(
        f"/api/v1/me/observations/{observation_id}/correct",
        json={"reason": "misgraded", "note": "I actually got this right"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["reason"] == "misgraded"

    history = client.get("/api/v1/me/observations", headers=headers).json()["items"]
    assert len(history) == 1
    assert history[0]["correction"]["reason"] == "misgraded"
    assert history[0]["correction"]["note"] == "I actually got this right"


def test_correcting_the_same_observation_twice_is_rejected(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=headers,
    )
    observation_id = client.get("/api/v1/me/observations", headers=headers).json()["items"][0]["observation_id"]

    first = client.post(
        f"/api/v1/me/observations/{observation_id}/correct", json={"reason": "irrelevant"}, headers=headers
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/me/observations/{observation_id}/correct", json={"reason": "misgraded"}, headers=headers
    )
    assert second.status_code == 409


def test_correcting_a_nonexistent_observation_404s(client, auth_headers):
    headers = auth_headers()
    resp = client.post(
        "/api/v1/me/observations/does-not-exist/correct", json={"reason": "misgraded"}, headers=headers
    )
    assert resp.status_code == 404


def test_correcting_another_accounts_observation_404s(client, auth_headers):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    _group, word = _setup_group_with_word(client, owner_headers)
    _enable_diagnosis(client, owner_headers)
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=owner_headers)
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=owner_headers,
    )
    observation_id = client.get("/api/v1/me/observations", headers=owner_headers).json()["items"][0]["observation_id"]

    other_headers = auth_headers(username="other", email="other@example.com")
    resp = client.post(
        f"/api/v1/me/observations/{observation_id}/correct", json={"reason": "misgraded"}, headers=other_headers
    )
    assert resp.status_code == 404


def test_history_endpoint_never_returns_another_accounts_observations(client, auth_headers):
    owner_headers = auth_headers(username="owner", email="owner@example.com")
    _group, word = _setup_group_with_word(client, owner_headers)
    _enable_diagnosis(client, owner_headers)
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=owner_headers)
    session_id = start.json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=owner_headers,
    )

    other_headers = auth_headers(username="other", email="other@example.com")
    resp = client.get("/api/v1/me/observations", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
