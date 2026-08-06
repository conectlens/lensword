"""Persisted intervention plans (issue #185 TODO 4).

Mirrors test_diagnosis_persistence_api.py's pattern for the diagnoses
table this one sits next to: repository round-trip, then an end-to-end
check that a genuinely diagnosable answer produces a real, persisted
plan, gated by the same learning_diagnosis_enabled flag diagnoses use.
There is no dedicated read endpoint in this pass (out of this issue's
scope) — plans are read back directly via the repository, the same way
test_knowledge_edges.py checks persistence without a bespoke endpoint.
"""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import InterventionOutcome, InterventionPlan
from app.infrastructure.repositories import (
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


def _plan(word_id: int, user_id: int, strategy: str = "contrast", **overrides) -> InterventionPlan:
    defaults = dict(
        word_id=word_id, user_id=user_id, diagnosis_outcome="exact_confusion", strategy=strategy,
        policy_version=1, eligible=True, rationale="r", planned_at=NOW,
    )
    defaults.update(overrides)
    return InterventionPlan(**defaults)


# --- Repository ---


def test_add_plan_and_list_plans_for_word_round_trip(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyInterventionRepository(db_session)

    repo.add_plan(_plan(word["id"], owner_id))
    plans = repo.list_plans_for_word(owner_id, word["id"])

    assert len(plans) == 1
    assert plans[0].strategy == "contrast"
    assert plans[0].diagnosis_outcome == "exact_confusion"
    assert plans[0].eligible is True
    assert plans[0].rationale == "r"


def test_list_plans_for_word_returns_empty_when_nothing_planned(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyInterventionRepository(db_session)

    assert repo.list_plans_for_word(owner_id, word["id"]) == []


def test_list_plans_for_word_is_append_only_newest_first(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyInterventionRepository(db_session)

    repo.add_plan(_plan(word["id"], owner_id, strategy="isolate", planned_at=datetime(2026, 8, 5, 9, 0)))
    repo.add_plan(_plan(word["id"], owner_id, strategy="contrast", planned_at=datetime(2026, 8, 6, 9, 0)))

    plans = repo.list_plans_for_word(owner_id, word["id"])
    assert [p.strategy for p in plans] == ["contrast", "isolate"]


def test_add_outcome_round_trips_through_the_domain_type(db_session, client, auth_headers):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers)
    repo = SqlAlchemyInterventionRepository(db_session)

    saved = repo.add_outcome(
        InterventionOutcome(
            word_id=word["id"], user_id=owner_id, strategy="contrast",
            completed=True, result="resolved", recorded_at=NOW,
        )
    )

    assert saved.strategy == "contrast"
    assert saved.completed is True
    assert saved.result == "resolved"


# --- End-to-end: review submission produces a real plan ---


def test_submitting_an_answer_that_abstains_produces_no_plan(client, auth_headers, db_session):
    """A single cold incorrect answer is genuinely insufficient evidence —
    the diagnosis abstains, and TODO 0's own rule is that an abstention
    produces no plan at all."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _group, word = _setup_group_with_word(client, headers, term="palabra", translation="word")
    _enable_diagnosis(client, headers)

    resp = _answer(client, headers, word)
    assert resp.status_code == 200

    repo = SqlAlchemyInterventionRepository(db_session)
    assert repo.list_plans_for_word(owner_id, word["id"]) == []


def test_a_real_exact_confusion_produces_a_contrast_plan(client, auth_headers, db_session):
    """End to end: a genuinely repeated confusion produces a non-abstention
    diagnosis, which produces a real, persisted CONTRAST plan."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
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

    plans = SqlAlchemyInterventionRepository(db_session).list_plans_for_word(owner_id, target["id"])
    assert len(plans) >= 1
    assert plans[0].strategy == "contrast"
    assert plans[0].diagnosis_outcome == "exact_confusion"
    assert plans[0].eligible is True


def test_no_plan_is_recorded_while_diagnosis_is_disabled(client, auth_headers, db_session):
    """ADR 0007: with the flag off, the request path never reaches the
    intervention_plans table at all — the same guarantee diagnoses,
    learning_observations, and knowledge_edges already have."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
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
    # Diagnosis left at its default (off).

    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")

    assert SqlAlchemyInterventionRepository(db_session).list_plans_for_word(owner_id, target["id"]) == []
