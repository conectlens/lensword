"""API boundary tests for the opt-in contrast-card surface (#206)."""


def test_contrast_cards_are_empty_until_both_opt_ins_are_enabled(client, auth_headers):
    headers = auth_headers()
    response = client.get("/api/v1/review/contrast-cards", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

    client.put(
        "/api/v1/recall-settings",
        json={"semantic_relatedness_enabled": True},
        headers=headers,
    )
    response = client.get("/api/v1/review/contrast-cards", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_contrast_answer_is_not_available_when_the_feature_is_disabled(client, auth_headers):
    headers = auth_headers()
    response = client.post(
        "/api/v1/review/contrast-cards/answer",
        json={
            "word_ids": [1, 2],
            "terms": ["borrow", "lend"],
            "relation": "antonym",
            "prompt": "How does borrow differ from lend?",
            "first_word_note": "receive",
            "second_word_note": "give",
            "distinction": "direction differs",
        },
        headers=headers,
    )
    assert response.status_code == 404
