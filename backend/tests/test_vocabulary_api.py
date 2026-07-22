def test_create_and_list_groups(client, auth_headers):
    headers = auth_headers()
    resp = client.post("/api/v1/groups", json={"name": "Spanish Verbs", "target_language": "Spanish"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Spanish Verbs"
    assert body["word_count"] == 0

    resp = client.get("/api/v1/groups", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_groups_are_isolated_per_user(client, auth_headers):
    headers_a = auth_headers(username="alex", email="alex@example.com")
    headers_b = auth_headers(username="sam", email="sam@example.com")

    client.post("/api/v1/groups", json={"name": "Alex Group", "target_language": "French"}, headers=headers_a)

    resp_b = client.get("/api/v1/groups", headers=headers_b)
    assert resp_b.json() == []


def test_cannot_access_another_users_group(client, auth_headers):
    headers_a = auth_headers(username="alex", email="alex@example.com")
    headers_b = auth_headers(username="sam", email="sam@example.com")

    group = client.post(
        "/api/v1/groups", json={"name": "Alex Group", "target_language": "French"}, headers=headers_a
    ).json()

    resp = client.get(f"/api/v1/groups/{group['id']}/words", headers=headers_b)
    assert resp.status_code == 403


def test_add_word_to_group_and_list_it(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "Spanish Verbs", "target_language": "Spanish"}, headers=headers
    ).json()

    resp = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={
            "term": "Correr",
            "target_language": "Spanish",
            "translations": ["To run"],
            "example_sentence": "Me gusta correr por la manana.",
            "mnemonic": "Sounds like 'currer' -- current runs fast",
            "category": "Verbs",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    word = resp.json()
    assert word["term"] == "Correr"
    assert word["translations"] == ["To run"]
    assert word["review_state"]["status"] == "new"
    assert word["review_state"]["strength"] == 0

    words = client.get(f"/api/v1/groups/{group['id']}/words", headers=headers).json()
    assert len(words) == 1

    group_after = client.get("/api/v1/groups", headers=headers).json()[0]
    assert group_after["word_count"] == 1


def test_update_word(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "German"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Hund", "target_language": "German", "translations": ["Dog"]},
        headers=headers,
    ).json()

    resp = client.put(
        f"/api/v1/words/{word['id']}",
        json={"term": "Hund", "target_language": "German", "translations": ["Dog", "Canine"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["translations"] == ["Dog", "Canine"]


def test_delete_word(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "German"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Hund", "target_language": "German", "translations": ["Dog"]},
        headers=headers,
    ).json()

    resp = client.delete(f"/api/v1/words/{word['id']}", headers=headers)
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/words/{word['id']}", headers=headers)
    assert resp.status_code == 404


def test_word_associations_add_and_remove(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "English"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Ephemeral", "target_language": "English", "translations": ["Fleeting"]},
        headers=headers,
    ).json()

    resp = client.patch(
        f"/api/v1/words/{word['id']}/associations",
        json={
            "add": [
                {"kind": "synonym", "value": "Fleeting"},
                {"kind": "synonym", "value": "Transient"},
                {"kind": "antonym", "value": "Permanent"},
                {"kind": "topic", "value": "Time"},
            ],
            "remove": [],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["synonyms"]) == {"Fleeting", "Transient"}
    assert body["antonyms"] == ["Permanent"]
    assert body["topics"] == ["Time"]

    resp = client.patch(
        f"/api/v1/words/{word['id']}/associations",
        json={"add": [], "remove": [{"kind": "synonym", "value": "Fleeting"}]},
        headers=headers,
    )
    assert resp.json()["synonyms"] == ["Transient"]


def test_create_room_and_place_word(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "Travel", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "La maleta", "target_language": "Spanish", "translations": ["The suitcase"]},
        headers=headers,
    ).json()

    room = client.post(
        "/api/v1/rooms", json={"group_id": group["id"], "name": "Travel Room", "icon": "luggage"}, headers=headers
    ).json()
    assert room["group_word_count"] == 1
    assert room["placements"] == []

    resp = client.post(
        f"/api/v1/rooms/{room['id']}/placements",
        json={"word_id": word["id"], "x_percent": 25.0, "y_percent": 40.0},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["placements"]) == 1
    assert body["placements"][0]["word_id"] == word["id"]
    assert body["placements"][0]["x_percent"] == 25.0


def test_cannot_place_word_from_a_different_group_in_a_room(client, auth_headers):
    headers = auth_headers()
    group_a = client.post(
        "/api/v1/groups", json={"name": "A", "target_language": "Spanish"}, headers=headers
    ).json()
    group_b = client.post(
        "/api/v1/groups", json={"name": "B", "target_language": "French"}, headers=headers
    ).json()
    word_b = client.post(
        f"/api/v1/groups/{group_b['id']}/words",
        json={"term": "Bonjour", "target_language": "French", "translations": ["Hello"]},
        headers=headers,
    ).json()
    room_a = client.post(
        "/api/v1/rooms", json={"group_id": group_a["id"], "name": "Room A"}, headers=headers
    ).json()

    resp = client.post(
        f"/api/v1/rooms/{room_a['id']}/placements",
        json={"word_id": word_b["id"], "x_percent": 10, "y_percent": 10},
        headers=headers,
    )
    assert resp.status_code == 400


def test_remove_placement(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Hola", "target_language": "Spanish", "translations": ["Hello"]},
        headers=headers,
    ).json()
    room = client.post("/api/v1/rooms", json={"group_id": group["id"], "name": "R"}, headers=headers).json()
    client.post(
        f"/api/v1/rooms/{room['id']}/placements",
        json={"word_id": word["id"], "x_percent": 10, "y_percent": 10},
        headers=headers,
    )

    resp = client.delete(f"/api/v1/rooms/{room['id']}/placements/{word['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["placements"] == []


def test_delete_group_also_removes_its_words(client, auth_headers):
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Hola", "target_language": "Spanish", "translations": ["Hello"]},
        headers=headers,
    ).json()

    resp = client.delete(f"/api/v1/groups/{group['id']}", headers=headers)
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/words/{word['id']}", headers=headers)
    assert resp.status_code == 404
