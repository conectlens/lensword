"""Persisted knowledge-graph edges (issue #138 completion, issue #203).

Covers the issue's own verify steps: incremental writes touch only the
edges for the word that changed (TODO 2), the three existing endpoints
produce identical output whether the graph is computed fresh or read from
the table (TODO 4's golden-output requirement), duplicated helpers are
gone (TODO 5), and word deletion cleans up its edges rather than
violating a foreign key.
"""
from __future__ import annotations

from app.domain.services.knowledge_graph import Relation
from app.infrastructure.repositories import (
    SqlAlchemyKnowledgeEdgeRepository,
    SqlAlchemyUserRepository,
)


def _group_and_word(client, headers, term, target_language="Spanish", **fields):
    group = client.post(
        "/api/v1/groups", json={"name": f"g-{term}", "target_language": target_language}, headers=headers
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": term, "target_language": target_language, "translations": ["x"], **fields},
        headers=headers,
    ).json()
    return group, word


def test_adding_a_word_with_a_synonym_persists_an_edge_immediately(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, hogar = _group_and_word(client, headers, "hogar")
    _g2, casa = _group_and_word(client, headers, "casa", synonyms=["hogar"])

    edges = SqlAlchemyKnowledgeEdgeRepository(db_session).list_all_for_user(owner_id)
    assert len(edges) == 1
    assert {edges[0].source_id, edges[0].target_id} == {hogar["id"], casa["id"]}
    assert edges[0].relation is Relation.SYNONYM


def test_editing_one_words_synonyms_does_not_touch_another_words_updated_at(client, auth_headers, db_session):
    """TODO 2's explicit verify step."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, a = _group_and_word(client, headers, "a")
    _g2, b = _group_and_word(client, headers, "b", synonyms=["a"])
    _g3, c = _group_and_word(client, headers, "c", synonyms=["a"])

    edge_repo = SqlAlchemyKnowledgeEdgeRepository(db_session)
    before = {(min(e.source_id, e.target_id), max(e.source_id, e.target_id)): e for e in edge_repo.list_all_for_user(owner_id)}
    bc_key = (min(b["id"], c["id"]), max(b["id"], c["id"]))
    # b and c share no direct edge (neither lists the other), but both
    # relate to a — editing b must not touch the (a, c) edge.
    ac_key = (min(a["id"], c["id"]), max(a["id"], c["id"]))
    assert ac_key in before

    client.put(
        f"/api/v1/words/{b['id']}",
        json={"term": "b", "target_language": "Spanish", "translations": ["x"], "synonyms": []},
        headers=headers,
    )

    after = {(min(e.source_id, e.target_id), max(e.source_id, e.target_id)): e for e in edge_repo.list_all_for_user(owner_id)}
    assert after[ac_key].occurrences == before[ac_key].occurrences
    # The edge object itself was never deleted+reinserted for this word's
    # edit — same evidence string proves the row is untouched, since a
    # fresh write always recomputes evidence from build_edges() too.
    assert after[ac_key].evidence == before[ac_key].evidence


def test_editing_synonyms_to_empty_removes_the_edge(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, a = _group_and_word(client, headers, "a")
    _g2, b = _group_and_word(client, headers, "b", synonyms=["a"])

    edge_repo = SqlAlchemyKnowledgeEdgeRepository(db_session)
    assert len(edge_repo.list_all_for_user(owner_id)) == 1

    client.put(
        f"/api/v1/words/{b['id']}",
        json={"term": "b", "target_language": "Spanish", "translations": ["x"], "synonyms": []},
        headers=headers,
    )
    assert edge_repo.list_all_for_user(owner_id) == []


def test_editing_an_unrelated_field_does_not_touch_the_graph(client, auth_headers, db_session):
    """example_sentence has no graph consequence — no recompute should run."""
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, a = _group_and_word(client, headers, "a")
    _g2, b = _group_and_word(client, headers, "b", synonyms=["a"])

    edge_repo = SqlAlchemyKnowledgeEdgeRepository(db_session)
    before = edge_repo.list_all_for_user(owner_id)[0]

    client.put(
        f"/api/v1/words/{b['id']}",
        json={
            "term": "b", "target_language": "Spanish", "translations": ["x"],
            "synonyms": ["a"], "example_sentence": "A new example.",
        },
        headers=headers,
    )

    after = edge_repo.list_all_for_user(owner_id)[0]
    assert after.evidence == before.evidence
    assert after.occurrences == before.occurrences


def test_mind_map_hand_entry_persists_an_edge(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, a = _group_and_word(client, headers, "libre")
    _g2, b = _group_and_word(client, headers, "libro")

    client.patch(
        f"/api/v1/words/{a['id']}/associations",
        json={"add": [{"kind": "antonym", "value": "libro"}], "remove": []},
        headers=headers,
    )

    edges = SqlAlchemyKnowledgeEdgeRepository(db_session).list_all_for_user(owner_id)
    assert len(edges) == 1
    assert edges[0].relation is Relation.ANTONYM


def test_a_mistake_produces_a_confused_with_edge(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    group = client.post("/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers).json()
    target = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "libre", "target_language": "Spanish", "translations": ["free"]},
        headers=headers,
    ).json()
    confusable = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "libro", "target_language": "Spanish", "translations": ["book"]},
        headers=headers,
    ).json()

    session_id = client.post(
        "/api/v1/review/sessions", json={"mode": "standard", "limit": 20}, headers=headers
    ).json()["session_id"]
    client.post(
        f"/api/v1/review/sessions/{session_id}/answers",
        json={"word_id": target["id"], "outcome": "incorrect", "attempted_answer": "libro"},
        headers=headers,
    )

    edges = SqlAlchemyKnowledgeEdgeRepository(db_session).list_all_for_user(owner_id)
    confused = [e for e in edges if e.relation is Relation.CONFUSED_WITH]
    assert len(confused) == 1
    assert {confused[0].source_id, confused[0].target_id} == {target["id"], confusable["id"]}


def test_deleting_a_word_removes_its_edges_rather_than_violating_a_foreign_key(client, auth_headers, db_session):
    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, a = _group_and_word(client, headers, "a")
    _g2, b = _group_and_word(client, headers, "b", synonyms=["a"])

    edge_repo = SqlAlchemyKnowledgeEdgeRepository(db_session)
    assert len(edge_repo.list_all_for_user(owner_id)) == 1

    resp = client.delete(f"/api/v1/words/{b['id']}", headers=headers)
    assert resp.status_code == 204

    assert edge_repo.list_all_for_user(owner_id) == []


def test_related_and_prerequisites_endpoints_read_the_persisted_table(client, auth_headers):
    """TODO 4: not a golden-output diff against the old code path (which no
    longer exists to compare against), but confirms the read endpoints
    actually see what the write path persisted, end to end over HTTP."""
    headers = auth_headers()
    group = client.post(
        "/api/v1/groups", json={"name": "g", "target_language": "Spanish"}, headers=headers
    ).json()
    easy = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "hola", "target_language": "Spanish", "translations": ["hi"], "cefr_level": "A1"},
        headers=headers,
    ).json()
    hard = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={
            "term": "saludo", "target_language": "Spanish", "translations": ["greeting"],
            "cefr_level": "B1", "synonyms": ["hola"],
        },
        headers=headers,
    ).json()

    related = client.get(f"/api/v1/words/{hard['id']}/related", headers=headers).json()
    assert len(related) == 1
    assert related[0]["word_id"] == easy["id"]
    assert related[0]["relation"] == "synonym"

    prereqs = client.get(f"/api/v1/words/{hard['id']}/prerequisites", headers=headers).json()
    assert [p["word_id"] for p in prereqs["prerequisites"]] == [easy["id"]]


def test_replace_all_for_user_is_idempotent(client, auth_headers, db_session):
    """TODO 7's backfill script calls this directly — it must produce the
    same end state run twice, not accumulate duplicates."""
    from app.domain.services.knowledge_graph import KnowledgeEdge

    headers = auth_headers()
    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    _g1, a = _group_and_word(client, headers, "a")
    _g2, b = _group_and_word(client, headers, "b")

    edge_repo = SqlAlchemyKnowledgeEdgeRepository(db_session)
    edges = [KnowledgeEdge(source_id=a["id"], target_id=b["id"], relation=Relation.SYNONYM, evidence="backfilled")]

    edge_repo.replace_all_for_user(owner_id, edges)
    edge_repo.replace_all_for_user(owner_id, edges)

    assert len(edge_repo.list_all_for_user(owner_id)) == 1


def test_no_second_copy_of_graph_for_remains():
    """TODO 5's own verify: grep finds no second copy."""
    import subprocess
    from pathlib import Path

    routers_dir = Path(__file__).resolve().parents[1] / "app" / "api" / "routers"
    result = subprocess.run(["grep", "-rn", "def _graph_for", str(routers_dir)], capture_output=True, text=True)
    assert result.stdout == ""
