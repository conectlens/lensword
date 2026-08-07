import pytest


def _enable(client, headers):
    response = client.put(
        "/api/v1/recall-settings",
        json={"ai_companion_enabled": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _start_session(client, headers):
    response = client.post(
        "/api/v1/companion/sessions",
        json={"connection_id": "desktop-1", "client_id": "host-a"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- Loop budgets ------------------------------------------------------------


def test_loop_start_then_reserve_advances_counters(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)

    started = client.post(
        f"/api/v1/companion/sessions/{session_id}/loop/start",
        json={"samples": 1, "tool_calls": 2},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    assert started.json()["samples"] == 0

    reserved = client.post(
        f"/api/v1/companion/sessions/{session_id}/loop/reserve",
        json={"kind": "sample", "amount": 1},
        headers=headers,
    )
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["samples"] == 1

    fetched = client.get(f"/api/v1/companion/sessions/{session_id}/loop", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["samples"] == 1


def test_loop_reserve_beyond_budget_is_a_conflict_and_persists_the_stop(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)
    client.post(f"/api/v1/companion/sessions/{session_id}/loop/start", json={"samples": 1}, headers=headers)
    client.post(
        f"/api/v1/companion/sessions/{session_id}/loop/reserve",
        json={"kind": "sample", "amount": 1},
        headers=headers,
    )
    denied = client.post(
        f"/api/v1/companion/sessions/{session_id}/loop/reserve",
        json={"kind": "sample", "amount": 1},
        headers=headers,
    )
    assert denied.status_code == 409, denied.text

    # The stop is durable: a fresh read shows the loop is still halted, not
    # just the one request that tripped the budget.
    fetched = client.get(f"/api/v1/companion/sessions/{session_id}/loop", headers=headers)
    assert fetched.json()["stopped_reason"] == "budget_exhausted"

    # And every further reservation - including an unrelated kind - is
    # refused too, which is what stops a red-teamed sampled reply from
    # triggering more tool calls once the loop has already stopped.
    also_denied = client.post(
        f"/api/v1/companion/sessions/{session_id}/loop/reserve",
        json={"kind": "tool", "amount": 1},
        headers=headers,
    )
    assert also_denied.status_code == 409


def test_loop_fail_three_times_stops_the_loop_for_repeated_failure(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)
    client.post(f"/api/v1/companion/sessions/{session_id}/loop/start", json={}, headers=headers)
    for _ in range(3):
        response = client.post(f"/api/v1/companion/sessions/{session_id}/loop/fail", headers=headers)
        assert response.status_code == 200
    assert response.json()["stopped_reason"] == "repeated_failure"


def test_loop_stop_accepts_only_explicit_reasons(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)
    client.post(f"/api/v1/companion/sessions/{session_id}/loop/start", json={}, headers=headers)

    ok = client.post(
        f"/api/v1/companion/sessions/{session_id}/loop/stop",
        json={"reason": "cancelled"},
        headers=headers,
    )
    assert ok.status_code == 200
    assert ok.json()["stopped_reason"] == "cancelled"

    session_id_2 = _start_session(client, headers)
    client.post(f"/api/v1/companion/sessions/{session_id_2}/loop/start", json={}, headers=headers)
    rejected = client.post(
        f"/api/v1/companion/sessions/{session_id_2}/loop/stop",
        json={"reason": "budget_exhausted"},
        headers=headers,
    )
    assert rejected.status_code == 422


def test_loop_requires_ai_companion_enabled(client, auth_headers):
    headers = auth_headers()
    response = client.post(
        "/api/v1/companion/sessions/does-not-matter/loop/start", json={}, headers=headers
    )
    assert response.status_code == 403


# --- Sampling provenance -----------------------------------------------------


def test_sampling_events_are_recorded_hash_chained_and_listable(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)

    first = client.post(
        f"/api/v1/companion/sessions/{session_id}/sampling-events",
        json={
            "requester": "desktop-app",
            "host_client_id": "claude-desktop",
            "model": "some-model",
            "prompt_template_version": "companion-v1",
            "source_facts_ref": "sha256:abc123",
            "validation_result": "accepted",
            "fallback_path": "sampling_succeeded",
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["event_hash"]

    second = client.post(
        f"/api/v1/companion/sessions/{session_id}/sampling-events",
        json={
            "requester": "desktop-app",
            "prompt_template_version": "companion-v1",
            "source_facts_ref": "sha256:def456",
            "validation_result": "sample contains a prohibited control or learning-truth claim",
            "fallback_path": "sampling_failed_fell_back_to_local_ai",
        },
        headers=headers,
    )
    assert second.status_code == 201
    # The chain links: the second event's previous_hash is unavailable in
    # the response schema, but a distinct hash from the first proves it is
    # not a static/constant value.
    assert second.json()["event_hash"] != first.json()["event_hash"]

    listed = client.get(f"/api/v1/companion/sessions/{session_id}/sampling-events", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 2


def test_sampling_event_rejects_unsupported_fallback_path(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)
    response = client.post(
        f"/api/v1/companion/sessions/{session_id}/sampling-events",
        json={
            "requester": "desktop-app",
            "prompt_template_version": "companion-v1",
            "source_facts_ref": "sha256:abc123",
            "validation_result": "accepted",
            "fallback_path": "made_up_path",
        },
        headers=headers,
    )
    assert response.status_code == 422


# --- Local-AI/deterministic reply fallback -----------------------------------


def test_reply_falls_back_to_deterministic_content_without_a_provider(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)

    response = client.post(
        f"/api/v1/companion/sessions/{session_id}/reply",
        json={
            "task": "Explain the observed contrast",
            "target_language": "Spanish",
            "intervention_type": "contrast",
            "evidence": [{"evidence_id": "obs-1", "fact": "borrow was answered as lend", "source": "review_observation"}],
            "allowed_claims": ["the supplied observation"],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "deterministic"
    assert body["evidence_ids"] == ["obs-1"]
    assert "borrow" in body["text"]
    # Never a bare diagnosis/mastery/retention claim (#187's boundary, which
    # this endpoint reuses rather than reimplements).
    assert "%" not in body["text"]


def test_reply_requires_at_least_one_evidence_item(client, auth_headers):
    headers = auth_headers()
    _enable(client, headers)
    session_id = _start_session(client, headers)
    response = client.post(
        f"/api/v1/companion/sessions/{session_id}/reply",
        json={
            "task": "Explain",
            "target_language": "Spanish",
            "intervention_type": "explanation",
            "evidence": [],
        },
        headers=headers,
    )
    assert response.status_code == 422
