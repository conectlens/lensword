"""API boundary tests for the opt-in contrast-card surface (#206)."""


def _enable_contrast_cards(client, headers):
    resp = client.put(
        "/api/v1/recall-settings",
        json={"semantic_relatedness_enabled": True, "contrast_cards_enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200


def test_answering_a_contrast_card_never_moves_a_real_words_due_at(client, auth_headers, db_session):
    """TODO 0's own verify clause, exercised end to end rather than on two
    freshly-constructed (and therefore trivially equal) `Word` objects: a
    real, persisted, already-reviewed word's `due_at` is byte-identical
    before and after answering a contrast card about it."""
    from app.infrastructure.repositories import SqlAlchemyWordRepository

    headers = auth_headers()
    _enable_contrast_cards(client, headers)
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    first = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "libre", "target_language": "Spanish", "translations": ["free"]},
        headers=headers,
    ).json()
    second = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "libro", "target_language": "Spanish", "translations": ["book"]},
        headers=headers,
    ).json()
    session = client.post("/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers).json()
    client.post(
        f"/api/v1/review/sessions/{session['session_id']}/answers",
        json={"word_id": first["id"], "outcome": "correct"},
        headers=headers,
    )

    before = SqlAlchemyWordRepository(db_session).get_by_id(first["id"]).review_state.due_at

    resp = client.post(
        "/api/v1/review/contrast-cards/answer",
        json={
            "word_ids": [first["id"], second["id"]],
            "terms": ["libre", "libro"],
            "relation": "antonym",
            "prompt": "How does libre differ from libro?",
            "first_word_note": "free",
            "second_word_note": "book",
            "distinction": "unrelated cognates",
        },
        headers=headers,
    )
    assert resp.status_code == 200

    after = SqlAlchemyWordRepository(db_session).get_by_id(first["id"]).review_state.due_at
    assert after == before


def test_contrast_cards_source_an_active_isolate_decision_over_the_graph(client, auth_headers, db_session):
    """#206 TODO 5, exercised end to end: a real #185 isolate plan
    suppresses even a strong graph-derived synonym/antonym candidate."""
    from datetime import timedelta

    from app.domain.services.diagnosis_contracts import InterventionPlan
    from app.domain.value_objects import utcnow
    from app.infrastructure.repositories import SqlAlchemyInterventionRepository, SqlAlchemyUserRepository

    headers = auth_headers()
    _enable_contrast_cards(client, headers)
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    first = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "vaca", "target_language": "Spanish", "translations": ["cow"]},
        headers=headers,
    ).json()
    second = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "vaso", "target_language": "Spanish", "translations": ["glass"]},
        headers=headers,
    ).json()
    # Directly seed established review state (stability/repetitions) rather
    # than round-tripping FSRS scheduling through real answers — this test
    # is about pair sourcing, not about how a word becomes established.
    from app.infrastructure.models import WordModel

    for word_id in (first["id"], second["id"]):
        model = db_session.get(WordModel, word_id)
        model.stability = 30.0
        model.repetitions = 3
    db_session.commit()

    SqlAlchemyInterventionRepository(db_session).add_plan(
        InterventionPlan(
            word_id=first["id"], user_id=owner_id, diagnosis_outcome="exact_confusion", strategy="isolate",
            policy_version=1, eligible=True, rationale="r", planned_at=utcnow() - timedelta(hours=1),
            second_word_id=second["id"],
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/review/contrast-cards", headers=headers)
    assert resp.status_code == 200
    pair = {first["id"], second["id"]}
    assert not any(set(card["word_ids"]) == pair for card in resp.json())


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
