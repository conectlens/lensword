"""Durable companion session boundaries for issue #193."""
import asyncio

import pytest

from app.domain.exceptions import ConcurrentModificationError
from app.domain.services.companion_sessions import (
    CompanionSessionStatus,
    CompanionTurn,
    CompanionTurnRole,
    deterministic_session_summary,
    extract_session_facts,
    summary_is_grounded,
)
from app.domain.value_objects import utcnow
from app.infrastructure.repositories import SqlAlchemyCompanionSessionRepository


def _enable(client, headers):
    response = client.put(
        "/api/v1/recall-settings",
        json={"ai_companion_enabled": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _start(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={
            "connection_id": "desktop-1",
            "client_id": "host-a",
            "goal": "technical vocabulary",
            "language": "Spanish",
            "consent_snapshot": {"read_profile": True},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_companion_session_is_disabled_by_default(client, auth_headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=auth_headers(),
    )
    assert response.status_code == 403


def test_session_turns_are_normalized_idempotent_and_exportable(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)

    turn = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "What does deploy mean?", "operation_id": "op-1"},
        headers=headers,
    )
    assert turn.status_code == 201, turn.text
    duplicate = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "different retry payload", "operation_id": "op-1"},
        headers=headers,
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["content"] == "What does deploy mean?"

    fetched = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers)
    assert fetched.status_code == 200
    assert len(fetched.json()["turns"]) == 1
    exported = client.get(f"/api/v1/companion/sessions/{session['id']}/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["format"] == "lensword.companion-session.v1"


def test_session_lifecycle_rejects_reopening_finished_sessions(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    paused = client.post(f"/api/v1/companion/sessions/{session['id']}/pause", headers=headers)
    assert paused.status_code == 200
    resumed = client.post(f"/api/v1/companion/sessions/{session['id']}/resume", headers=headers)
    assert resumed.status_code == 200
    finished = client.post(f"/api/v1/companion/sessions/{session['id']}/finish", headers=headers)
    assert finished.status_code == 200
    reopened = client.post(f"/api/v1/companion/sessions/{session['id']}/resume", headers=headers)
    assert reopened.status_code == 409


def test_deleting_content_preserves_redacted_session_metadata(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "assistant", "content": "A bounded answer", "operation_id": "op-2"},
        headers=headers,
    )
    deleted = client.delete(f"/api/v1/companion/sessions/{session['id']}/content", headers=headers)
    assert deleted.status_code == 204
    fetched = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers).json()
    assert fetched["turns"] == []
    assert fetched["summary"] == "[content deleted]"


def test_structured_activity_is_separate_from_free_chat_and_never_claims_mastery(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    started = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities",
        json={
            "activity_type": "recall",
            "prompt": "Recall the meaning of deploy.",
            "expected_evaluation": {"kind": "presence"},
            "operation_id": "activity-1",
        },
        headers=headers,
    )
    assert started.status_code == 201, started.text
    activity = started.json()
    assert activity["status"] == "active"

    response = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity['id']}/response",
        json={"response": "to deploy is to release"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["result"]["evaluator"] == "deterministic_presence_v1"
    assert "mastery" not in body["result"]

    finished = client.post(
        f"/api/v1/companion/sessions/{session['id']}/activities/{activity['id']}/finish",
        headers=headers,
    )
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"


# --- TODO 3: real optimistic concurrency (#193) -----------------------------


def test_stale_revision_write_is_rejected_not_silently_overwritten(client, auth_headers, db_session):
    """The bug this closes: `update()` used to blindly overwrite whatever
    row it found, so two readers of the same revision could both "succeed"
    and the second write would silently clobber the first. Now the second
    writer's stale expected_revision must be refused."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]

    repo = SqlAlchemyCompanionSessionRepository(db_session)
    reader_a = repo.get(user_id, session["id"])
    reader_b = repo.get(user_id, session["id"])
    assert reader_a.revision == reader_b.revision == 1

    reader_a.pause()
    updated = repo.update(reader_a, expected_revision=1)
    assert updated.revision == 2
    assert updated.status is CompanionSessionStatus.PAUSED

    reader_b.resume()
    with pytest.raises(ConcurrentModificationError):
        repo.update(reader_b, expected_revision=1)

    # The winning write is what is actually stored — not silently clobbered
    # by the loser, and not left half-applied either.
    stored = repo.get(user_id, session["id"])
    assert stored.revision == 2
    assert stored.status is CompanionSessionStatus.PAUSED


def test_transfer_reassigns_control_and_is_owner_authorized(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    assert session["connection_id"] == "desktop-1"
    assert session["client_id"] == "host-a"

    transferred = client.post(
        f"/api/v1/companion/sessions/{session['id']}/transfer",
        json={"connection_id": "mobile-1", "client_id": "host-b"},
        headers=headers,
    )
    assert transferred.status_code == 200, transferred.text
    body = transferred.json()["session"]
    assert body["connection_id"] == "mobile-1"
    assert body["client_id"] == "host-b"
    assert body["revision"] == 2
    # The session's other state — status, goal, language — is untouched by
    # a transfer; only who controls it next changes.
    assert body["status"] == "active"
    assert body["goal"] == "technical vocabulary"


def test_transfer_of_a_finished_session_is_rejected(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    finished = client.post(f"/api/v1/companion/sessions/{session['id']}/finish", headers=headers)
    assert finished.status_code == 200

    transfer = client.post(
        f"/api/v1/companion/sessions/{session['id']}/transfer",
        json={"connection_id": "mobile-1", "client_id": "host-b"},
        headers=headers,
    )
    assert transfer.status_code == 409


def test_cross_client_continuation_preserves_every_turn_in_order(client, auth_headers):
    """The issue's core scenario: start in client A, hand control to client
    B, continue back on A — no turn lost, none duplicated, all ordered."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)  # "started" on client A (desktop-1/host-a)

    a1 = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "hello from A", "operation_id": "a-1"},
        headers=headers,
    )
    assert a1.status_code == 201

    transferred = client.post(
        f"/api/v1/companion/sessions/{session['id']}/transfer",
        json={"connection_id": "mobile-1", "client_id": "host-b"},
        headers=headers,
    )
    assert transferred.status_code == 200

    b1 = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "assistant", "content": "reply from B", "operation_id": "b-1"},
        headers=headers,
    )
    assert b1.status_code == 201

    # Control returns to client A.
    back_to_a = client.post(
        f"/api/v1/companion/sessions/{session['id']}/transfer",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=headers,
    )
    assert back_to_a.status_code == 200

    a2 = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "back on A", "operation_id": "a-2"},
        headers=headers,
    )
    assert a2.status_code == 201

    fetched = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers).json()
    assert [t["content"] for t in fetched["turns"]] == ["hello from A", "reply from B", "back on A"]
    assert fetched["connection_id"] == "desktop-1"


def test_a_revoked_session_rejects_further_writes(client, auth_headers):
    """Revocation is a one-way door (#193 TODO 4/5): once revoked, no
    client — regardless of which one held control — may add turns or
    resume it. The session row itself (status, prior turns) stays readable
    for export/audit, matching TODO 4's provider-neutral export."""
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "before revoke", "operation_id": "op-r1"},
        headers=headers,
    )

    revoked = client.post(f"/api/v1/companion/sessions/{session['id']}/revoke", headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()["session"]["status"] == "revoked"

    blocked_turn = client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "after revoke", "operation_id": "op-r2"},
        headers=headers,
    )
    assert blocked_turn.status_code == 409

    blocked_resume = client.post(f"/api/v1/companion/sessions/{session['id']}/resume", headers=headers)
    assert blocked_resume.status_code == 409

    blocked_transfer = client.post(
        f"/api/v1/companion/sessions/{session['id']}/transfer",
        json={"connection_id": "mobile-1", "client_id": "host-b"},
        headers=headers,
    )
    assert blocked_transfer.status_code == 409

    # Still readable — a revoked session is not erased, only closed to
    # further writes (see test_deleting_content_preserves_redacted_session
    # _metadata for the separate, explicit right-to-erasure path).
    still_readable = client.get(f"/api/v1/companion/sessions/{session['id']}", headers=headers)
    assert still_readable.status_code == 200
    assert len(still_readable.json()["turns"]) == 1


# --- TODO 2: real summarization (#193) --------------------------------------


def test_finishing_a_session_generates_a_deterministic_summary(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "What does deploy mean?", "operation_id": "op-s1"},
        headers=headers,
    )
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "assistant", "content": "To deploy is to release.", "activity_id": "act-1", "operation_id": "op-s2"},
        headers=headers,
    )

    finished = client.post(f"/api/v1/companion/sessions/{session['id']}/finish", headers=headers)
    assert finished.status_code == 200
    summary = finished.json()["session"]["summary"]
    assert summary is not None
    assert "turn_count: 2" in summary
    assert "act-1" in summary
    assert "technical vocabulary" in summary  # the session's goal


def test_summary_can_be_regenerated_without_ending_the_session(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session = _start(client, headers)
    client.post(
        f"/api/v1/companion/sessions/{session['id']}/turns",
        json={"role": "user", "content": "hola", "operation_id": "op-1"},
        headers=headers,
    )

    regenerated = client.post(f"/api/v1/companion/sessions/{session['id']}/summary", headers=headers)
    assert regenerated.status_code == 200
    body = regenerated.json()["session"]
    assert body["status"] == "active"  # unlike finish, status is untouched
    assert "turn_count: 1" in body["summary"]


def test_extract_session_facts_is_bounded_and_literal():
    now = utcnow()
    session_kwargs = dict(
        id="s1", user_id=1, connection_id="c", client_id="h", goal="learn verbs", language="Spanish",
        group_id=3, difficulty="beginner", active_activity=None, consent_snapshot={}, summary=None,
        status=CompanionSessionStatus.ACTIVE, revision=1, created_at=now, updated_at=now,
    )
    from app.domain.services.companion_sessions import CompanionSession

    session = CompanionSession(**session_kwargs)
    turns = [
        CompanionTurn(1, "s1", CompanionTurnRole.USER, "hola", "act-1", None, now),
        CompanionTurn(2, "s1", CompanionTurnRole.ASSISTANT, "hello", None, None, now),
    ]
    facts = extract_session_facts(session, turns)
    assert "goal: learn verbs" in facts
    assert "language: Spanish" in facts
    assert "group_id: 3" in facts
    assert "turn_count: 2" in facts
    assert "user_turns: 1" in facts
    assert "assistant_turns: 1" in facts
    assert "activities_touched: act-1" in facts

    summary = deterministic_session_summary(facts)
    assert "learn verbs" in summary and len(summary) <= 4000


def test_grounded_summary_accepts_paraphrase_but_rejects_fabrication():
    facts = ("goal: order food", "turn_count: 4", "activities_touched: act-1, act-2")
    paraphrased = "The learner worked on the goal of order food across four exchanges, touching act-1 and act-2."
    assert summary_is_grounded(paraphrased, facts) is True

    fabricated_number = "The learner completed 99 turns."
    assert summary_is_grounded(fabricated_number, facts) is False

    fabricated_activity = "The learner also touched act-99, which never happened."
    assert summary_is_grounded(fabricated_activity, facts) is False

    assert summary_is_grounded("", facts) is False
    assert summary_is_grounded("   ", facts) is False


def test_summarize_use_case_falls_back_when_ai_summary_is_ungrounded():
    """An AI provider that invents a detail must never be trusted — the use
    case rejects it and falls back to the deterministic summary rather than
    propagating the fabrication (#193 TODO 2)."""
    from app.application.use_cases.companion_sessions import SummarizeCompanionSessionUseCase
    from app.domain.services.companion_sessions import CompanionSession

    now = utcnow()
    session = CompanionSession(
        id="s1", user_id=1, connection_id="c", client_id="h", goal="order food", language="French",
        group_id=None, difficulty=None, active_activity=None, consent_snapshot={}, summary=None,
        status=CompanionSessionStatus.ACTIVE, revision=1, created_at=now, updated_at=now,
    )

    class _FakeRepo:
        def list_turns(self, user_id, session_id, limit=100):
            return [CompanionTurn(1, "s1", CompanionTurnRole.USER, "Bonjour", None, None, now)]

    class _FabricatingProvider:
        async def generate_field(self, field, term, source_language, target_language, context=None):
            return "You completed 500 turns and reached mastery."

    summary, source = asyncio.run(
        SummarizeCompanionSessionUseCase(_FakeRepo(), _FabricatingProvider()).build_summary(session)
    )
    assert source == "deterministic"
    assert "500" not in summary
    assert "order food" in summary


def test_summarize_use_case_accepts_a_grounded_ai_summary():
    from app.application.use_cases.companion_sessions import SummarizeCompanionSessionUseCase
    from app.domain.services.companion_sessions import CompanionSession

    now = utcnow()
    session = CompanionSession(
        id="s1", user_id=1, connection_id="c", client_id="h", goal="order food", language="French",
        group_id=None, difficulty=None, active_activity=None, consent_snapshot={}, summary=None,
        status=CompanionSessionStatus.ACTIVE, revision=1, created_at=now, updated_at=now,
    )

    class _FakeRepo:
        def list_turns(self, user_id, session_id, limit=100):
            return [CompanionTurn(1, "s1", CompanionTurnRole.USER, "Bonjour", None, None, now)]

    class _HonestProvider:
        async def generate_field(self, field, term, source_language, target_language, context=None):
            return "The learner practiced their goal of order food in one exchange."

    summary, source = asyncio.run(
        SummarizeCompanionSessionUseCase(_FakeRepo(), _HonestProvider()).build_summary(session)
    )
    assert source == "ai"
    assert "order food" in summary


def test_summarize_use_case_falls_back_when_provider_is_unavailable():
    from app.application.use_cases.companion_sessions import SummarizeCompanionSessionUseCase
    from app.domain.exceptions import AIProviderUnavailableError
    from app.domain.services.companion_sessions import CompanionSession

    now = utcnow()
    session = CompanionSession(
        id="s1", user_id=1, connection_id="c", client_id="h", goal=None, language=None,
        group_id=None, difficulty=None, active_activity=None, consent_snapshot={}, summary=None,
        status=CompanionSessionStatus.ACTIVE, revision=1, created_at=now, updated_at=now,
    )

    class _FakeRepo:
        def list_turns(self, user_id, session_id, limit=100):
            return []

    class _DownProvider:
        async def generate_field(self, field, term, source_language, target_language, context=None):
            raise AIProviderUnavailableError()

    summary, source = asyncio.run(
        SummarizeCompanionSessionUseCase(_FakeRepo(), _DownProvider()).build_summary(session)
    )
    assert source == "deterministic"
    assert summary
