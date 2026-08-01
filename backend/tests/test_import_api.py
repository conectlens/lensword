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


def test_parse_csv_and_plain_text_files(client, auth_headers):
    headers = auth_headers()
    csv_response = client.post('/api/v1/imports/parse', files={'file': ('words.csv', 'term,translation\nhola,hello\n', 'text/csv')}, headers=headers)
    text_response = client.post('/api/v1/imports/parse', files={'file': ('words.txt', 'merhaba\n', 'text/plain')}, headers=headers)
    assert csv_response.json()['records'] == [{'term': 'hola', 'translations': ['hello'], 'definition': None, 'part_of_speech': None, 'cefr_level': None, 'pronunciation': None}]
    assert text_response.json()['records'][0]['term'] == 'merhaba'
