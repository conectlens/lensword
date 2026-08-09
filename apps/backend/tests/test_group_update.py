"""Editing a group's language as well as its name (issue #337).

Two claims carry the weight here. A group's language and its words'
languages are independent facts, so retargeting the container must not
restate the vocabulary inside it. And the cached language profile is
derived from which languages the learner studies, so a language change has
to drop it while a rename must not — a cache that keeps answering with the
old language set is the failure this feature could plausibly introduce.
"""
from __future__ import annotations

from app.application.use_cases.mcp_dev_workflow import LANGUAGE_PROFILE_CACHE
from app.domain.value_objects import utcnow


def _group(client, headers, name="Spanish 1", language="Spanish"):
    response = client.post(
        "/api/v1/groups", json={"name": name, "target_language": language}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch(client, headers, group_id: int, body: dict):
    return client.patch(f"/api/v1/groups/{group_id}", json=body, headers=headers)


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def test_a_rename_only_body_still_works(client, auth_headers):
    """Every existing caller sends exactly this and must be unaffected."""
    headers = auth_headers()
    group = _group(client, headers)

    response = _patch(client, headers, group["id"], {"name": "Spanish Verbs"})

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Spanish Verbs"
    assert response.json()["target_language"] == "Spanish"


def test_the_language_can_be_changed_on_its_own(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)

    response = _patch(client, headers, group["id"], {"target_language": "French"})

    assert response.status_code == 200, response.text
    assert response.json()["target_language"] == "French"
    assert response.json()["name"] == "Spanish 1"


def test_both_fields_change_together(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)

    response = _patch(
        client, headers, group["id"], {"name": "French Basics", "target_language": "French"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "French Basics"
    assert response.json()["target_language"] == "French"


def test_an_empty_body_is_rejected_rather_than_silently_doing_nothing(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)

    assert _patch(client, headers, group["id"], {}).status_code == 422


def test_an_unsupported_language_is_rejected(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)

    assert _patch(client, headers, group["id"], {"target_language": "Klingon"}).status_code == 422


def test_words_keep_their_own_language_when_the_group_is_retargeted(client, auth_headers):
    """A word card records what language that word is in, and retargeting
    its container does not make that untrue."""
    headers = auth_headers()
    group = _group(client, headers)
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=headers,
    ).json()

    assert _patch(client, headers, group["id"], {"target_language": "French"}).status_code == 200

    groups = client.get("/api/v1/groups", headers=headers).json()
    assert next(g for g in groups if g["id"] == group["id"])["target_language"] == "French"

    words = client.get(f"/api/v1/groups/{group['id']}/words", headers=headers).json()
    assert next(w for w in words if w["id"] == word["id"])["target_language"] == "Spanish"


def test_changing_the_language_drops_the_cached_language_profile(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)
    user_id = _user_id(client, headers)
    LANGUAGE_PROFILE_CACHE.put(user_id, "stale", utcnow())

    assert _patch(client, headers, group["id"], {"target_language": "German"}).status_code == 200

    assert LANGUAGE_PROFILE_CACHE.get(user_id, utcnow()) is None


def test_renaming_alone_leaves_the_cached_language_profile_intact(client, auth_headers):
    """The profile is derived from languages, so a rename cannot change it
    and dropping the cache would be work with no effect to justify it."""
    headers = auth_headers()
    group = _group(client, headers)
    user_id = _user_id(client, headers)
    LANGUAGE_PROFILE_CACHE.put(user_id, "still-valid", utcnow())

    assert _patch(client, headers, group["id"], {"name": "Renamed"}).status_code == 200

    assert LANGUAGE_PROFILE_CACHE.get(user_id, utcnow()) == "still-valid"


def test_setting_the_same_language_is_not_treated_as_a_change(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)
    user_id = _user_id(client, headers)
    LANGUAGE_PROFILE_CACHE.put(user_id, "still-valid", utcnow())

    assert _patch(client, headers, group["id"], {"target_language": "Spanish"}).status_code == 200

    assert LANGUAGE_PROFILE_CACHE.get(user_id, utcnow()) == "still-valid"


def test_another_account_cannot_edit_the_group(client, auth_headers):
    owner = auth_headers(username="alex", email="alex@example.com")
    intruder = auth_headers(username="sam", email="sam@example.com")
    group = _group(client, owner)

    response = _patch(client, intruder, group["id"], {"target_language": "French"})

    assert response.status_code in {403, 404}
