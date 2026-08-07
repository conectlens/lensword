"""Intervention plan action endpoints (issue #185 TODO 4)."""
from __future__ import annotations


def _setup_confused_pair(client, headers):
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
    resp = client.put("/api/v1/recall-settings", json={"learning_diagnosis_enabled": True}, headers=headers)
    assert resp.status_code == 200
    return target


def _answer(client, headers, word, **fields):
    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    session_id = start.json()["session_id"]
    return client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect", **fields},
        headers=headers,
    )


def test_list_active_interventions_returns_a_real_plan(client, auth_headers):
    headers = auth_headers()
    target = _setup_confused_pair(client, headers)
    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")

    resp = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers)
    assert resp.status_code == 200
    plans = resp.json()
    assert len(plans) == 1
    assert plans[0]["strategy"] == "isolate"


def test_rejecting_a_plan_removes_it_from_the_active_list(client, auth_headers):
    headers = auth_headers()
    target = _setup_confused_pair(client, headers)
    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")
    plan_id = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()[0]["id"]

    resp = client.post(f"/api/v1/words/{target['id']}/interventions/{plan_id}/reject", headers=headers)
    assert resp.status_code == 200

    active = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()
    assert active == []


def test_postponing_a_plan_keeps_it_active(client, auth_headers):
    headers = auth_headers()
    target = _setup_confused_pair(client, headers)
    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")
    plan_id = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()[0]["id"]

    resp = client.post(f"/api/v1/words/{target['id']}/interventions/{plan_id}/postpone", headers=headers)
    assert resp.status_code == 200

    active = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()
    assert len(active) == 1


def test_choosing_an_alternative_creates_a_new_plan_and_closes_the_old_one(client, auth_headers):
    headers = auth_headers()
    target = _setup_confused_pair(client, headers)
    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")
    plan_id = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()[0]["id"]

    resp = client.post(
        f"/api/v1/words/{target['id']}/interventions/{plan_id}/alternative",
        json={"strategy": "spatial_anchor"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["strategy"] == "spatial_anchor"

    active = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()
    assert len(active) == 1
    assert active[0]["strategy"] == "spatial_anchor"


def test_choosing_an_unknown_strategy_is_rejected(client, auth_headers):
    headers = auth_headers()
    target = _setup_confused_pair(client, headers)
    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")
    plan_id = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()[0]["id"]

    resp = client.post(
        f"/api/v1/words/{target['id']}/interventions/{plan_id}/alternative",
        json={"strategy": "not_a_real_strategy"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_acting_on_another_users_plan_is_a_404(client, auth_headers):
    headers = auth_headers()
    target = _setup_confused_pair(client, headers)
    for _ in range(2):
        _answer(client, headers, target, attempted_answer="libro")
    plan_id = client.get(f"/api/v1/words/{target['id']}/interventions", headers=headers).json()[0]["id"]

    other_headers = auth_headers(username="jordan", email="jordan@example.com")
    other_group = client.post(
        "/api/v1/groups", json={"name": "og", "target_language": "Spanish"}, headers=other_headers
    ).json()
    other_word = client.post(
        f"/api/v1/groups/{other_group['id']}/words",
        json={"term": "otro", "target_language": "Spanish", "translations": ["other"]},
        headers=other_headers,
    ).json()

    resp = client.post(
        f"/api/v1/words/{other_word['id']}/interventions/{plan_id}/reject", headers=other_headers
    )
    assert resp.status_code == 404
