from app.api.deps import get_ai_provider
from app.domain.services.ai_provider import WordEnrichment
from app.main import app


class Provider:
    async def enrich_word(self, term, source_language, target_language):
        return WordEnrichment(term=term, target_language=target_language, translations=['translation'], definitions=['definition'], part_of_speech='noun', cefr_level='B1', pronunciation='sound', provider='stub', model='model')


def test_preview_deduplicates_and_ai_cleans_then_commits(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = lambda: Provider()
    try:
        headers = auth_headers(); group = client.post('/api/v1/groups', json={'name':'G','target_language':'Spanish'}, headers=headers).json()
        preview = client.post('/api/v1/imports/preview', json={'group_id':group['id'], 'enrich_with_ai':True, 'records':[{'term':'house'}, {'term':'House'}]}, headers=headers)
        assert preview.status_code == 200
        records = preview.json()['records']; assert [record['status'] for record in records] == ['ai_cleaned', 'duplicate']
        committed = client.post('/api/v1/imports/commit', json={'group_id':group['id'], 'records':records}, headers=headers)
        assert committed.json() == {'added': 1}
        assert client.get(f"/api/v1/groups/{group['id']}/words", headers=headers).json()[0]['translations'] == ['translation']
    finally: app.dependency_overrides.pop(get_ai_provider, None)


class ProviderWithAssociations:
    """Issue #202 TODO 3: unlike `Provider` above, this stub also returns
    synonyms/antonyms/topics — what a real enrichment call already produces
    (issue #202's actual defect was these being produced and then dropped)."""

    async def enrich_word(self, term, source_language, target_language):
        return WordEnrichment(
            term=term, target_language=target_language, translations=['translation'],
            definitions=['definition'], part_of_speech='noun', cefr_level='B1', pronunciation='sound',
            synonyms=['syn'], antonyms=['ant'], tags=['topic-a'], topics=['topic-a'],
            provider='stub', model='model',
        )


def test_import_preview_and_commit_agree_on_synonyms_antonyms_and_topics(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = lambda: ProviderWithAssociations()
    try:
        headers = auth_headers()
        group = client.post('/api/v1/groups', json={'name': 'G', 'target_language': 'Spanish'}, headers=headers).json()
        preview = client.post(
            '/api/v1/imports/preview',
            json={'group_id': group['id'], 'enrich_with_ai': True, 'records': [{'term': 'house'}]},
            headers=headers,
        )
        record = preview.json()['records'][0]
        assert record['synonyms'] == ['syn']
        assert record['antonyms'] == ['ant']
        assert record['topics'] == ['topic-a']

        client.post('/api/v1/imports/commit', json={'group_id': group['id'], 'records': [record]}, headers=headers)
        word = client.get(f"/api/v1/groups/{group['id']}/words", headers=headers).json()[0]
        # Preview and the committed record must agree field-for-field — the
        # defect this issue fixes was exactly a field the preview could show
        # and the commit would silently drop.
        assert word['synonyms'] == record['synonyms']
        assert word['antonyms'] == record['antonyms']
        assert word['topics'] == record['topics']
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


def test_ai_enrichment_produces_a_non_empty_knowledge_graph_end_to_end(client, auth_headers):
    """Issue #202 TODO 7: the test that would have caught the whole defect.
    Enrich (via import) -> persist -> the real /related endpoint's
    build_edges call -> a non-empty edge list. Before this issue's fix,
    every step up to the last one worked and the graph was still empty,
    because nothing wrote the AI's associations onto the word."""

    class SynonymProvider:
        async def enrich_word(self, term, source_language, target_language):
            # "casa" is enriched as a synonym of "hogar" — the second word
            # already exists with that exact term, so a real edge should
            # form between them once both are persisted.
            return WordEnrichment(
                term=term, target_language=target_language, translations=['home'],
                synonyms=['hogar'], provider='stub', model='model',
            )

    app.dependency_overrides[get_ai_provider] = lambda: SynonymProvider()
    try:
        headers = auth_headers()
        group = client.post('/api/v1/groups', json={'name': 'G', 'target_language': 'Spanish'}, headers=headers).json()
        hogar = client.post(
            f"/api/v1/groups/{group['id']}/words",
            json={'term': 'hogar', 'target_language': 'Spanish', 'translations': ['home']},
            headers=headers,
        ).json()

        preview = client.post(
            '/api/v1/imports/preview',
            json={'group_id': group['id'], 'enrich_with_ai': True, 'records': [{'term': 'casa'}]},
            headers=headers,
        )
        record = preview.json()['records'][0]
        assert record['synonyms'] == ['hogar']
        client.post('/api/v1/imports/commit', json={'group_id': group['id'], 'records': [record]}, headers=headers)

        related = client.get(f"/api/v1/words/{hogar['id']}/related", headers=headers)
        assert related.status_code == 200
        edges = related.json()
        assert edges, "expected a non-empty knowledge graph after AI-enriched import"
        assert edges[0]['term'] == 'casa'
        assert edges[0]['relation'] == 'synonym'
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)


def test_parse_csv_and_plain_text_files(client, auth_headers):
    headers = auth_headers()
    csv_response = client.post('/api/v1/imports/parse', files={'file': ('words.csv', 'term,translation\nhola,hello\n', 'text/csv')}, headers=headers)
    text_response = client.post('/api/v1/imports/parse', files={'file': ('words.txt', 'merhaba\n', 'text/plain')}, headers=headers)
    assert csv_response.json()['records'] == [{'term': 'hola', 'translations': ['hello'], 'definition': None, 'part_of_speech': None, 'cefr_level': None, 'pronunciation': None}]
    assert text_response.json()['records'][0]['term'] == 'merhaba'
