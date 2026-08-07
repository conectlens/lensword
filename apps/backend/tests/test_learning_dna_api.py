"""Learning DNA endpoints (issue #186 TODO 4): efficacy conclusions and the
stated modality preference, reachable by a real client.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.diagnosis_contracts import InterventionPlan, LearningObservation
from app.domain.value_objects import ReviewOutcome, SessionMode
from app.infrastructure.models import WordModel
from app.infrastructure.repositories import (
    SqlAlchemyInterventionRepository,
    SqlAlchemyLearningObservationRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)


def _setup_word(client, headers, db_session):
    group = client.post(
        "/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    client.put("/api/v1/recall-settings", json={"learning_diagnosis_enabled": True}, headers=headers)
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    # The word was just created via the API, i.e. "now" — backdate it so the
    # fixture below (plan + delayed observations) lands safely in the past,
    # inside `GetEfficacyConclusionsUseCase`'s lookback window and never in
    # the future relative to the real wall clock the endpoint reads.
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
    word_model = db_session.get(WordModel, word["id"])
    word_model.created_at = past
    db_session.flush()
    return owner_id, word["id"], past


def _observation(index: int, *, word_id, user_id, observed_at, correct, plan_ref=None):
    return LearningObservation(
        observation_id=f"obs-{index}",
        word_id=word_id,
        user_id=user_id,
        outcome=ReviewOutcome.CORRECT if correct else ReviewOutcome.INCORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=observed_at,
        intervention_plan_ref=plan_ref,
    )


def test_efficacy_endpoint_is_empty_for_a_fresh_account(client, auth_headers):
    headers = auth_headers()
    resp = client.get("/api/v1/me/learning-dna/efficacy", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_efficacy_endpoint_reports_a_real_scoped_comparison(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id, word_id, word_created_at = _setup_word(client, headers, db_session)

    plan_time = word_created_at + timedelta(days=1)
    SqlAlchemyInterventionRepository(db_session).add_plan(
        InterventionPlan(
            word_id=word_id, user_id=owner_id, diagnosis_outcome="weak_acquisition",
            strategy="contrast", policy_version=2, eligible=True, rationale="r", planned_at=plan_time,
        )
    )

    observation_repo = SqlAlchemyLearningObservationRepository(db_session)
    # Ten observations on the same word, alternating organic (control) and
    # plan-linked (intervention), evenly interleaved so exposure_count and
    # prior-mastery stay comparable between arms (avoiding a confound this
    # fixture isn't trying to test) — intervention answers are all correct,
    # organic answers mostly wrong, a genuine effect.
    for i in range(10):
        is_intervention = i % 2 == 1
        # Distinct calendar days so each observation is its own exposure
        # (same-day repeats are meant to collapse — see
        # intervention_attribution's exposure_id — but these ten are meant
        # to count as ten independent delayed checkpoints).
        observed_at = plan_time + timedelta(days=7 + i)
        observation_repo.add(
            _observation(
                i,
                word_id=word_id,
                user_id=owner_id,
                observed_at=observed_at,
                correct=True if is_intervention else i < 3,
                plan_ref="p1" if is_intervention else None,
            )
        )

    resp = client.get("/api/v1/me/learning-dna/efficacy", headers=headers)
    assert resp.status_code == 200
    estimates = resp.json()
    assert len(estimates) >= 1
    contrast = [e for e in estimates if e["intervention_type"] == "contrast"]
    assert len(contrast) == 1
    estimate = contrast[0]
    assert estimate["context"]["language"] == "Spanish"
    assert estimate["intervention_samples"] + estimate["control_samples"] == 10
    # This fixture's arms are balanced in exposure_count/prior_mastery and
    # genuinely different in outcome (all-correct vs mostly-wrong), so the
    # comparison should clear both the minimum-sample and confounding
    # checks and land on a real, traceable measurement — not an abstention.
    assert estimate["status"] == "MEASURED"
    assert estimate["intervention_rate"] == 1.0
    assert estimate["control_rate"] == pytest.approx(0.4)
    assert estimate["effect"] == pytest.approx(0.6)
    assert estimate["recommendation"] is not None
    assert "contrast" in estimate["recommendation"]
    assert estimate["period_start"] is not None
    assert estimate["valid_until"] is not None


def test_modality_preference_round_trips_and_stays_separate_from_efficacy(client, auth_headers):
    headers = auth_headers()

    initial = client.get("/api/v1/me/learning-dna/modality-preference", headers=headers)
    assert initial.status_code == 200
    assert initial.json() is None

    posted = client.post(
        "/api/v1/me/learning-dna/modality-preference", json={"modality": "image"}, headers=headers
    )
    assert posted.status_code == 200
    assert posted.json()["modality"] == "image"

    fetched = client.get("/api/v1/me/learning-dna/modality-preference", headers=headers)
    assert fetched.json()["modality"] == "image"

    # Stating a new preference is a new record, not an edit — the latest
    # one wins for "current".
    client.post("/api/v1/me/learning-dna/modality-preference", json={"modality": "audio"}, headers=headers)
    latest = client.get("/api/v1/me/learning-dna/modality-preference", headers=headers)
    assert latest.json()["modality"] == "audio"


def test_modality_preference_is_scoped_per_account(client, auth_headers):
    owner = auth_headers()
    other = auth_headers(username="jordan", email="jordan@example.com")

    client.post("/api/v1/me/learning-dna/modality-preference", json={"modality": "image"}, headers=owner)

    other_pref = client.get("/api/v1/me/learning-dna/modality-preference", headers=other)
    assert other_pref.json() is None
