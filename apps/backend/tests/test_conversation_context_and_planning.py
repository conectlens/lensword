"""Adaptive conversation context assembly and bounded session planning
(issue #194 TODO 2 / TODO 4).
"""
from __future__ import annotations

from datetime import timedelta

from app.application.use_cases.conversation_context import AssembleConversationContextUseCase
from app.domain.services.companion_activities import ActivityType
from app.domain.services.conversation_context import (
    ActiveWordFact,
    ConfusionFact,
    DueItemFact,
    build_conversation_context,
)
from app.domain.services.companion_planning import generate_activity_plan
from app.domain.services.diagnosis_contracts import Diagnosis, InterventionPlan
from app.domain.value_objects import utcnow
from app.infrastructure.models import WordModel
from app.infrastructure.repositories import (
    SqlAlchemyCompanionSessionRepository,
    SqlAlchemyDiagnosisRepository,
    SqlAlchemyGroupRepository,
    SqlAlchemyInterventionRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)


def _enable(client, headers):
    assert client.put("/api/v1/recall-settings", json={"ai_companion_enabled": True}, headers=headers).status_code == 200


# --- Pure domain bounding ----------------------------------------------------


def test_build_conversation_context_bounds_every_section_independently():
    active = [ActiveWordFact(word_id=i, term=f"w{i}", target_language="Spanish") for i in range(50)]
    due = [DueItemFact(word_id=i, term=f"d{i}", target_language="Spanish") for i in range(50)]
    confusion = [ConfusionFact(word_id=i, outcome="x", confidence=0.5, sample_size=3) for i in range(50)]

    context = build_conversation_context("session-1", "  order food  ", active, due, confusion, None)

    assert context.goal == "order food"
    assert len(context.active_words) == 10
    assert len(context.due_items) == 10
    assert len(context.confusion) == 5


def test_generate_activity_plan_ranks_confusion_backed_due_items_first():
    due = [DueItemFact(word_id=1, term="a", target_language="Spanish"), DueItemFact(word_id=2, term="b", target_language="Spanish")]
    confusion = [ConfusionFact(word_id=2, outcome="exact_confusion", confidence=0.8, sample_size=5)]
    context = build_conversation_context("s1", "goal", [], due, confusion, None)

    plan = generate_activity_plan(context, max_activities=5)

    assert plan.items[0].word_id == 2
    assert plan.items[0].activity_type is ActivityType.RECALL
    assert plan.max_writes == len(plan.items)
    assert plan.confirmed is False


def test_generate_activity_plan_never_exceeds_the_hard_cap():
    due = [DueItemFact(word_id=i, term=f"d{i}", target_language="Spanish") for i in range(20)]
    context = build_conversation_context("s1", None, [], due, [], None)

    plan = generate_activity_plan(context, max_activities=100)

    from app.domain.services.companion_planning import MAX_PLANNED_ACTIVITIES

    assert len(plan.items) == MAX_PLANNED_ACTIVITIES


# --- Application-level context assembly against real repositories -----------


def test_assemble_conversation_context_use_case_surfaces_due_active_confusion_and_intervention(
    client, auth_headers, db_session
):
    headers = auth_headers()
    _enable(client, headers)
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id

    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    due_word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "confundir", "target_language": "Spanish", "translations": ["to confuse"]},
        headers=headers,
    ).json()
    active_word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()
    # `active_word` has been reviewed before (repetitions > 0) and is not
    # currently due; `due_word` has never been reviewed and stays due.
    active_model = db_session.get(WordModel, active_word["id"])
    active_model.repetitions = 3
    active_model.due_at = utcnow() + timedelta(days=5)
    db_session.flush()

    diagnosis_repo = SqlAlchemyDiagnosisRepository(db_session)
    diagnosis_repo.add(
        Diagnosis(
            word_id=due_word["id"], user_id=owner_id, outcome="exact_confusion",
            evidence=(), confidence=0.7, rules_version=1, diagnosed_at=utcnow(), sample_size=4,
        )
    )
    intervention_repo = SqlAlchemyInterventionRepository(db_session)
    intervention_repo.add_plan(
        InterventionPlan(
            word_id=due_word["id"], user_id=owner_id, diagnosis_outcome="exact_confusion",
            strategy="isolate", policy_version=1, eligible=True, rationale="Practice in isolation.",
            planned_at=utcnow(),
        )
    )
    db_session.commit()

    session = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "c1", "client_id": "h1", "goal": "confuse less", "group_id": group["id"]},
        headers=headers,
    ).json()

    use_case = AssembleConversationContextUseCase(
        SqlAlchemyCompanionSessionRepository(db_session), SqlAlchemyWordRepository(db_session),
        SqlAlchemyGroupRepository(db_session), diagnosis_repo, intervention_repo,
    )
    context = use_case.execute(owner_id, session["id"])

    assert context.goal == "confuse less"
    assert {fact.word_id for fact in context.due_items} == {due_word["id"]}
    assert {fact.word_id for fact in context.active_words} == {active_word["id"]}
    assert len(context.confusion) == 1
    assert context.confusion[0].word_id == due_word["id"]
    assert context.selected_intervention is not None
    assert context.selected_intervention.word_id == due_word["id"]
    assert context.selected_intervention.strategy == "isolate"


# --- Session planning through the real endpoints, confirmation-gated --------


def test_generate_plan_then_confirm_creates_activities_only_when_confirmed(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(client, headers)
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    )
    session = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "c1", "client_id": "h1", "group_id": group["id"]},
        headers=headers,
    ).json()
    task = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks",
        json={"task_type": "plan_generation", "total_units": 1},
        headers=headers,
    ).json()

    generated = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks/{task['id']}/generate-plan",
        json={"max_activities": 5},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    plan_result = generated.json()["result"]
    assert plan_result["confirmed"] is False
    assert len(plan_result["items"]) >= 1

    # Refusing confirmation must not create any activity.
    refused = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks/{task['id']}/confirm-plan",
        json={"confirmed": False},
        headers=headers,
    )
    assert refused.status_code == 409
    assert client.get(f"/api/v1/companion/sessions/{session['id']}/tasks/{task['id']}", headers=headers).json()["result"]["confirmed"] is False

    confirmed = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks/{task['id']}/confirm-plan",
        json={"confirmed": True},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["result"]
    assert result["confirmed"] is True
    assert len(result["created_activity_ids"]) == len(plan_result["items"])

    # A second confirmation is rejected — a plan executes at most once.
    again = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks/{task['id']}/confirm-plan",
        json={"confirmed": True},
        headers=headers,
    )
    assert again.status_code == 409


def test_generate_plan_rejects_a_non_plan_generation_task(client, auth_headers, db_session):
    headers = auth_headers()
    _enable(client, headers)
    session = client.post(
        "/api/v1/companion/sessions", json={"connection_id": "c1", "client_id": "h1"}, headers=headers
    ).json()
    task = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks",
        json={"task_type": "extraction", "total_units": 1},
        headers=headers,
    ).json()

    response = client.post(
        f"/api/v1/companion/sessions/{session['id']}/tasks/{task['id']}/generate-plan",
        json={"max_activities": 5},
        headers=headers,
    )
    assert response.status_code == 409
