"""Mnemonic strength endpoint (issue #185 TODO 3)."""
from __future__ import annotations


def _setup_word_with_mnemonic(client, headers):
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "gato", "target_language": "Spanish", "translations": ["cat"]},
        headers=headers,
    ).json()
    note = client.post(f"/api/v1/words/{word['id']}/mnemonics", json={"text": "sounds like 'got a cat'"}, headers=headers).json()
    return word, note


def test_a_fresh_mnemonic_has_insufficient_data(client, auth_headers):
    headers = auth_headers()
    word, note = _setup_word_with_mnemonic(client, headers)

    resp = client.get(f"/api/v1/words/{word['id']}/mnemonics/{note['id']}/strength", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "insufficient_data"


def test_a_downvoted_mnemonic_is_weak_regardless_of_sample_size(client, auth_headers):
    headers = auth_headers()
    word, note = _setup_word_with_mnemonic(client, headers)

    resp = client.post(
        f"/api/v1/words/{word['id']}/mnemonics/{note['id']}/vote", json={"upvote": False}, headers=headers
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/words/{word['id']}/mnemonics/{note['id']}/strength", headers=headers)
    assert resp.json()["verdict"] == "weak"


def test_strength_for_another_users_word_is_forbidden(client, auth_headers):
    headers = auth_headers()
    word, note = _setup_word_with_mnemonic(client, headers)

    other_headers = auth_headers(username="jordan", email="jordan@example.com")
    resp = client.get(f"/api/v1/words/{word['id']}/mnemonics/{note['id']}/strength", headers=other_headers)
    assert resp.status_code == 403
