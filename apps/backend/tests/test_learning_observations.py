"""Rich learning telemetry and the immutable evidence model (#180, issue #182).

Covers the issue's verify steps: legacy payloads still succeed, enriched
payloads round-trip, duplicate/retried submissions yield exactly one
observation per operation ID, and — per ADR 0007 — nothing is written at
all while learning_diagnosis_enabled is off.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.services.diagnosis_contracts import LearningObservation
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
    assert resp.json()["learning_diagnosis_enabled"] is True


def _start_and_answer(client, headers, word, **answer_fields):
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    return client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "correct", **answer_fields},
        headers=headers,
    )


def test_a_legacy_payload_still_succeeds_with_diagnosis_enabled(client, auth_headers):
    """TODO 0's first verify: a client that sends none of the new fields
    stays valid even when the account has diagnosis on."""
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)

    resp = _start_and_answer(client, headers, word)
    assert resp.status_code == 200


def test_no_observation_is_recorded_while_diagnosis_is_disabled(client, auth_headers, db_session):
    """ADR 0007: with the flag off, the request path never reaches
    learning_observations, even if the client sends the richer fields."""
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    # Diagnosis left at its default (off).

    resp = _start_and_answer(
        client, headers, word,
        response_time_ms=1200, prompt_direction="term_to_translation", modality="typing",
    )
    assert resp.status_code == 200

    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    observations = SqlAlchemyLearningObservationRepository(db_session).list_for_word(owner_id, word["id"])
    assert observations == []


def test_an_enriched_payload_round_trips_when_diagnosis_is_enabled(client, auth_headers, db_session):
    """TODO 0's second verify, and TODO 2 (modality/intervention
    provenance): every richer field submitted is what gets persisted."""
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)

    resp = _start_and_answer(
        client, headers, word,
        response_time_ms=2400,
        attempted_answer="Hallo",
        operation_id="op-1",
        prompt_direction="translation_to_term",
        hint_used=True,
        answer_format="typed",
        modality="typing",
        intervention_plan_ref="plan-42",
        self_reported_confidence=0.4,
    )
    assert resp.status_code == 200

    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    observations = SqlAlchemyLearningObservationRepository(db_session).list_for_word(owner_id, word["id"])
    assert len(observations) == 1
    obs = observations[0]
    assert obs.outcome == ReviewOutcome.CORRECT
    assert obs.session_mode == SessionMode.STANDARD
    assert obs.response_time_ms == 2400
    assert obs.attempted_answer == "Hallo"
    assert obs.operation_id == "op-1"
    assert obs.prompt_direction == "translation_to_term"
    assert obs.hint_used is True
    assert obs.answer_format == "typed"
    assert obs.modality == "typing"
    assert obs.intervention_plan_ref == "plan-42"
    assert obs.self_reported_confidence == 0.4


def test_a_retried_submission_with_the_same_operation_id_is_recorded_once(client, auth_headers, db_session):
    """TODO 1: duplicate, retried submissions yield exactly one acknowledged
    observation per operation ID."""
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)

    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]

    for _ in range(3):
        resp = client.post(
            f"/api/v1/review/sessions/{session_id}/answers",
            json={"word_id": word["id"], "outcome": "correct", "operation_id": "retry-me"},
            headers=headers,
        )
        assert resp.status_code == 200

    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    observations = SqlAlchemyLearningObservationRepository(db_session).list_for_word(owner_id, word["id"])
    assert len(observations) == 1


def test_submissions_without_an_operation_id_are_each_recorded_separately(client, auth_headers, db_session):
    """A missing operation_id means no idempotency guarantee was
    requested — three plain submissions are three real answers, not
    duplicates of each other."""
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)
    _enable_diagnosis(client, headers)

    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]

    for _ in range(3):
        client.post(
            f"/api/v1/review/sessions/{session_id}/answers",
            json={"word_id": word["id"], "outcome": "correct"},
            headers=headers,
        )

    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    observations = SqlAlchemyLearningObservationRepository(db_session).list_for_word(owner_id, word["id"])
    assert len(observations) == 3


# --- Repository query axes (TODO 4: word, pair, time window, modality, intervention) ---


def _observation(user_id, word_id, **overrides) -> LearningObservation:
    defaults = dict(
        observation_id=f"obs-{word_id}-{overrides.get('operation_id', 'x')}",
        word_id=word_id,
        user_id=user_id,
        outcome=ReviewOutcome.INCORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=datetime(2026, 8, 6, 9, 0),
    )
    defaults.update(overrides)
    return LearningObservation(**defaults)


def test_repository_queries_cover_word_pair_window_modality_and_intervention(client, auth_headers, db_session):
    auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyLearningObservationRepository(db_session)

    repo.add(_observation(owner_id, 1, operation_id="a", modality="typing", intervention_plan_ref="plan-1", observed_at=datetime(2026, 8, 1, 9, 0)))
    repo.add(_observation(owner_id, 2, operation_id="b", modality="speaking", observed_at=datetime(2026, 8, 3, 9, 0)))
    repo.add(_observation(owner_id, 3, operation_id="c", observed_at=datetime(2026, 8, 5, 9, 0)))

    assert {o.word_id for o in repo.list_for_word(owner_id, 1)} == {1}
    assert {o.word_id for o in repo.list_for_pair(owner_id, 1, 2)} == {1, 2}
    assert {o.word_id for o in repo.list_in_window(owner_id, datetime(2026, 8, 2), datetime(2026, 8, 4))} == {2}
    assert {o.word_id for o in repo.list_by_modality(owner_id, "typing")} == {1}
    assert {o.word_id for o in repo.list_by_intervention(owner_id, "plan-1")} == {1}


def test_find_by_operation_returns_none_for_an_unseen_operation_id(client, auth_headers, db_session):
    auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    repo = SqlAlchemyLearningObservationRepository(db_session)
    assert repo.find_by_operation(owner_id, "never-submitted") is None
