"""Semantic separation applied at the import preview (issue #204 TODO 3)."""
from __future__ import annotations

from app.api.deps import get_ai_provider
from app.domain.services.ai_provider import WordEnrichment
from app.main import app


class _ThemedProvider:
    """Colours share a topic; everything else does not — a themed batch."""

    _TOPICS = {"red": ["colours"], "blue": ["colours"], "green": ["colours"], "yellow": ["colours"]}

    async def enrich_word(self, term, source_language, target_language):
        return WordEnrichment(
            term=term, target_language=target_language, translations=[f"{term}-t"],
            definitions=["d"], part_of_speech="noun", cefr_level="B1", pronunciation="p",
            topics=self._TOPICS.get(term, []), provider="stub", model="model",
        )


def _group(client, headers):
    return client.post("/api/v1/groups", json={"name": "G", "target_language": "Spanish"}, headers=headers).json()


def _enable_semantic_relatedness(client, headers):
    resp = client.put("/api/v1/recall-settings", json={"semantic_relatedness_enabled": True}, headers=headers)
    assert resp.status_code == 200, resp.text


def _preview(client, headers, group_id, terms, enrich=True):
    return client.post(
        "/api/v1/imports/preview",
        json={"group_id": group_id, "enrich_with_ai": enrich, "records": [{"term": t} for t in terms]},
        headers=headers,
    )


def test_the_flag_off_leaves_the_original_order_untouched(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)
    app.dependency_overrides[get_ai_provider] = lambda: _ThemedProvider()
    try:
        resp = _preview(client, headers, group["id"], ["red", "blue", "green", "yellow", "table"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["diversity_ordering_applied"] is False
        assert [r["term"] for r in body["records"]] == ["red", "blue", "green", "yellow", "table"]
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


def test_a_themed_batch_is_spread_apart_with_the_flag_on(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)
    _enable_semantic_relatedness(client, headers)
    app.dependency_overrides[get_ai_provider] = lambda: _ThemedProvider()
    try:
        resp = _preview(client, headers, group["id"], ["red", "blue", "green", "yellow", "table", "run", "happy"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["diversity_ordering_applied"] is True

        terms = [r["term"] for r in body["records"]]
        colour_positions = sorted(terms.index(c) for c in ("red", "blue", "green", "yellow"))
        assert all(b - a > 1 for a, b in zip(colour_positions, colour_positions[1:]))
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


def test_without_enrichment_there_is_nothing_to_detect_relatedness_from(client, auth_headers):
    """No AI enrichment means empty synonyms/antonyms/topics on every
    record — the policy runs but has no signal to act on, so the order is
    left as submitted rather than reordered on nothing."""
    headers = auth_headers()
    group = _group(client, headers)
    _enable_semantic_relatedness(client, headers)

    resp = _preview(client, headers, group["id"], ["red", "blue", "green", "yellow"], enrich=False)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["diversity_ordering_applied"] is False
    assert [r["term"] for r in body["records"]] == ["red", "blue", "green", "yellow"]


def test_a_word_related_to_already_studied_vocabulary_is_deferred_with_a_visible_reason(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)
    client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "kitten", "target_language": "Spanish", "translations": ["x"], "topics": ["colours"]},
        headers=headers,
    )
    _enable_semantic_relatedness(client, headers)
    app.dependency_overrides[get_ai_provider] = lambda: _ThemedProvider()
    try:
        resp = _preview(client, headers, group["id"], ["red", "table"])
        assert resp.status_code == 200, resp.text
        body = resp.json()

        red = next(r for r in body["records"] if r["term"] == "red")
        table = next(r for r in body["records"] if r["term"] == "table")
        assert red["deferred_reason"] is not None
        assert table["deferred_reason"] is None
        # Deferred records land after non-deferred ones.
        terms = [r["term"] for r in body["records"]]
        assert terms.index("red") > terms.index("table")
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


def test_duplicates_are_excluded_from_reordering_and_kept_at_the_end(client, auth_headers):
    headers = auth_headers()
    group = _group(client, headers)
    _enable_semantic_relatedness(client, headers)
    app.dependency_overrides[get_ai_provider] = lambda: _ThemedProvider()
    try:
        resp = _preview(client, headers, group["id"], ["red", "blue", "red"])
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["records"][-1]["status"] == "duplicate"
        assert body["records"][-1]["term"] == "red"
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)
