from app.api.deps import get_ai_provider_for_user as get_ai_provider
from app.domain.services.ai_provider import WordEnrichment
from app.main import app


class StubProvider:
    async def enrich_word(self, term, source_language, target_language):
        return WordEnrichment(
            term=term,
            target_language=target_language,
            translations=["hola"],
            definitions=["a greeting"],
            part_of_speech="noun",
            cefr_level="A1",
            pronunciation="ola",
            examples=["Hola, Ana."],
            synonyms=["saludo"],
            antonyms=[],
            collocations=["decir hola"],
            tags=["greeting"],
            mnemonic="hello = hola",
            category="travel",
            confidence=0.9,
            provider="stub",
            model="test-model",
        )

    async def translate_in_context(self, word, sentence, source_language, target_language):
        return await self.enrich_word(word, source_language, target_language)

    async def generate_field(self, field, term, source_language, target_language, context=None):
        return f"{field} for {term}"


def test_enrich_returns_the_complete_contract(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = lambda: StubProvider()
    response = client.post(
        "/api/v1/ai/enrich",
        json={"term": "hello", "source_language": "English", "target_language": "Spanish"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["translations"] == ["hola"]
    assert body["definitions"] == ["a greeting"]
    assert body["provider"] == "stub"
    assert body["model"] == "test-model"


def test_context_translation_and_field_regeneration_are_authenticated(client, auth_headers):
    app.dependency_overrides[get_ai_provider] = lambda: StubProvider()
    headers = auth_headers()
    translated = client.post(
        "/api/v1/ai/translate-in-context",
        json={"word": "bank", "sentence": "I sat by the river bank.", "target_language": "Spanish"},
        headers=headers,
    )
    regenerated = client.post(
        "/api/v1/ai/regenerate-field",
        json={"field": "mnemonic", "term": "bank", "target_language": "Spanish"},
        headers=headers,
    )
    assert translated.status_code == 200
    assert regenerated.json() == {"field": "mnemonic", "value": "mnemonic for bank"}
