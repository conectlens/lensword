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


def test_cannot_start_session_with_no_due_words(client, auth_headers):
    headers = auth_headers()
    resp = client.post("/api/v1/review/sessions", json={"mode": "standard"}, headers=headers)
    assert resp.status_code == 409


def test_full_review_session_flow_updates_word_and_user_stats(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)

    start = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers)
    assert start.status_code == 201
    session_id = start.json()["session_id"]
    assert len(start.json()["words"]) == 1
    assert start.json()["words"][0]["id"] == word["id"]

    answer = client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "correct", "response_time_ms": 1200},
        headers=headers,
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["was_new_word_learned"] is True
    assert body["word"]["review_state"]["strength"] == 15
    assert body["word"]["review_state"]["repetitions"] == 1

    complete = client.post(
        f"/api/v1/review/sessions/{session_id}/complete",
        json={"new_words_learned_count": 1},
        headers=headers,
    )
    assert complete.status_code == 200
    summary = complete.json()
    assert summary["words_reviewed"] == 1
    assert summary["correct_count"] == 1
    assert summary["incorrect_count"] == 0
    assert summary["accuracy_percent"] == 100.0
    assert summary["new_words_learned"] == 1

    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["streak_days"] == 1
    assert me["total_words_learned"] == 1


def test_incorrect_answer_lowers_strength_and_resets_repetitions(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)

    session_id = client.post(
        "/api/v1/review/sessions", json={"mode": "standard"}, headers=headers
    ).json()["session_id"]

    answer = client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "incorrect"},
        headers=headers,
    )
    body = answer.json()
    assert body["was_new_word_learned"] is False
    assert body["word"]["review_state"]["strength"] == 0  # clamped at 0, started at 0
    assert body["word"]["review_state"]["repetitions"] == 0


def test_cannot_answer_in_another_users_session(client, auth_headers):
    headers_a = auth_headers(username="alex", email="alex@example.com")
    headers_b = auth_headers(username="sam", email="sam@example.com")
    _group, word = _setup_group_with_word(client, headers_a)

    session_id = client.post(
        "/api/v1/review/sessions", json={"mode": "standard"}, headers=headers_a
    ).json()["session_id"]

    resp = client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "correct"},
        headers=headers_b,
    )
    assert resp.status_code == 403


def test_weekly_progress_reflects_completed_sessions(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers)

    session_id = client.post(
        "/api/v1/review/sessions", json={"mode": "standard"}, headers=headers
    ).json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": word["id"], "outcome": "correct"},
        headers=headers,
    )
    client.post(f"/api/v1/review/sessions/{session_id}/complete", json={}, headers=headers)

    resp = client.get("/api/v1/review/weekly-progress", headers=headers)
    assert resp.status_code == 200
    counts = resp.json()["counts_by_day"]
    assert sum(counts.values()) == 1


def test_mnemonic_lifecycle(client, auth_headers):
    headers = auth_headers()
    _group, word = _setup_group_with_word(client, headers, term="Ephemeral", translation="Fleeting")

    resp = client.post(
        f"/api/v1/words/{word['id']}/mnemonics", json={"text": "Sounds like 'ephemeral wall'"}, headers=headers
    )
    assert resp.status_code == 201
    note = resp.json()
    assert note["upvotes"] == 0
    assert note["score"] == 0

    resp = client.post(
        f"/api/v1/words/{word['id']}/mnemonics/{note['id']}/vote", json={"upvote": True}, headers=headers
    )
    assert resp.json()["upvotes"] == 1
    assert resp.json()["score"] == 1

    resp = client.get(f"/api/v1/words/{word['id']}/mnemonics", headers=headers)
    assert len(resp.json()) == 1


def test_recall_settings_roundtrip(client, auth_headers):
    headers = auth_headers()
    defaults = client.get("/api/v1/recall-settings", headers=headers).json()
    assert defaults["intensity"] == 3

    resp = client.put(
        "/api/v1/recall-settings",
        json={"enabled": True, "intensity": 5, "walking_mode_enabled": True, "walking_steps_threshold": 2000},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["intensity"] == 5
    assert resp.json()["walking_mode_enabled"] is True

    again = client.get("/api/v1/recall-settings", headers=headers).json()
    assert again["intensity"] == 5


def test_profile_overview_reports_badge_progress(client, auth_headers):
    headers = auth_headers()
    resp = client.get("/api/v1/profile", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["badges"]) == 5
    assert all(b["earned"] is False for b in body["badges"])
