"""Verification, history and bulk editing over HTTP (issue #140).

The rule that costs something is the one worth driving end to end: a model
rewriting a verified field ends the verification. Keeping the badge is the
tempting option, and it is how a verified badge comes to vouch for text nobody
read.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


def _group(client, headers) -> int:
    resp = client.post(
        "/api/v1/groups", json={"name": "Spanish", "target_language": "Spanish"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _word(client, headers, group_id: int, term: str = "gato", **extra) -> dict:
    payload = {"term": term, "target_language": "Spanish", "translations": ["cat"], **extra}
    resp = client.post(f"/api/v1/groups/{group_id}/words", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ai_word(client, headers, group_id: int, **extra) -> dict:
    return _word(
        client, headers, group_id,
        ai_provider="ollama", ai_model="llama3.2", ai_confidence=0.8, **extra,
    )


def _put(client, headers, word: dict, **changes):
    body = {
        "term": word["term"],
        "target_language": "Spanish",
        "translations": word["translations"],
        "definition": word.get("definition"),
        **changes,
    }
    return client.put(f"/api/v1/words/{word['id']}", json=body, headers=headers)


# --- Verification state ----------------------------------------------------


def test_a_model_written_card_starts_unverified(client, headers):
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id)

    assert word["ai_state"] == "unverified"


def test_a_hand_written_card_is_human_not_unverified(client, headers):
    """There is nothing to verify — nobody claimed a model wrote it."""
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    assert word["ai_state"] == "human"


def test_verifying_a_model_card_marks_it_checked(client, headers):
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id)

    resp = client.post(f"/api/v1/words/{word['id']}/verify", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "verified"
    assert resp.json()["ai_verified_at"] is not None


def test_verifying_a_hand_written_card_is_refused(client, headers):
    """Letting the flag be set anyway would make "verified" mean two different
    things depending on the card."""
    group_id = _group(client, headers)
    word = _word(client, headers, group_id)

    assert client.post(f"/api/v1/words/{word['id']}/verify", headers=headers).status_code == 409


def test_verification_can_be_withdrawn(client, headers):
    """Someone who realises they approved a card too quickly needs a way to say
    so."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id)
    client.post(f"/api/v1/words/{word['id']}/verify", headers=headers)

    resp = client.delete(f"/api/v1/words/{word['id']}/verify", headers=headers)

    assert resp.json()["state"] == "unverified"


def test_a_verified_state_is_visible_on_the_card(client, headers):
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id)
    client.post(f"/api/v1/words/{word['id']}/verify", headers=headers)

    fetched = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()

    assert fetched["ai_state"] == "verified"


def test_verifying_another_accounts_card_is_refused(client, auth_headers):
    alex = auth_headers()
    group_id = _group(client, alex)
    word = _ai_word(client, alex, group_id)

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.post(f"/api/v1/words/{word['id']}/verify", headers=sam).status_code in {403, 404}


# --- Verification survival -------------------------------------------------


def test_a_human_edit_keeps_verification(client, headers):
    """They are the one who checked it; their own correction does not make it
    unchecked."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="a cat")
    client.post(f"/api/v1/words/{word['id']}/verify", headers=headers)

    _put(client, headers, word, definition="a small cat")

    fetched = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert fetched["ai_state"] == "verified"


def test_re_enrichment_ends_verification(client, headers, db_session):
    """The badge says a person read this text. After a model rewrites it that
    is no longer true of what is on screen, so the badge has to go.

    Driven through the use case rather than HTTP: no route lets a caller claim
    to be a model, which is deliberate — the source of an edit is decided by
    the code path that made it, not by the request.
    """
    from app.application.use_cases.vocabulary import UpdateWordUseCase, WordInput
    from app.domain.services.ai_provenance import EditSource
    from app.domain.value_objects import SupportedLanguage
    from app.infrastructure.repositories import (
        SqlAlchemyGroupRepository,
        SqlAlchemyUserRepository,
        SqlAlchemyWordRepository,
        SqlAlchemyWordRevisionRepository,
    )

    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="a cat")
    verified = client.post(f"/api/v1/words/{word['id']}/verify", headers=headers).json()
    assert verified["state"] == "verified"

    owner_id = SqlAlchemyUserRepository(db_session).get_by_email("alex@example.com").id
    word_repo = SqlAlchemyWordRepository(db_session)
    UpdateWordUseCase(
        word_repo, SqlAlchemyGroupRepository(db_session), SqlAlchemyWordRevisionRepository(db_session)
    ).execute(
        owner_id,
        word["id"],
        WordInput(
            term=word["term"],
            target_language=SupportedLanguage.SPANISH,
            translations=word["translations"],
            definition="a small domesticated feline",
        ),
        source=EditSource.AI,
    )

    assert word_repo.get_by_id(word["id"]).ai_verified_at is None


def test_an_edit_that_changes_nothing_does_not_strip_the_badge(client, headers):
    """Re-saving an untouched card must not quietly unverify it."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="a cat")
    client.post(f"/api/v1/words/{word['id']}/verify", headers=headers)

    _put(client, headers, word, definition="a cat")

    fetched = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert fetched["ai_state"] == "verified"


# --- History ---------------------------------------------------------------


def test_editing_a_tracked_field_records_what_it_said_before(client, headers):
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="a cat")

    _put(client, headers, word, definition="a small cat")

    history = client.get(f"/api/v1/words/{word['id']}/history", headers=headers).json()
    assert len(history) == 1
    assert history[0]["field"] == "definition"
    assert history[0]["before_value"] == "a cat"
    assert history[0]["after_value"] == "a small cat"
    assert history[0]["source"] == "human"


def test_an_edit_that_changes_nothing_records_nothing(client, headers):
    """Otherwise every save fills the history with entries describing nothing."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="a cat")

    _put(client, headers, word, definition="a cat")

    assert client.get(f"/api/v1/words/{word['id']}/history", headers=headers).json() == []


def test_an_untracked_field_is_not_recorded(client, headers):
    """`term` is what makes a card that card, not a model's claim about the
    language."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id)

    _put(client, headers, word, term="perro")

    history = client.get(f"/api/v1/words/{word['id']}/history", headers=headers).json()
    assert all(entry["field"] != "term" for entry in history)


def test_history_comes_back_newest_first(client, headers):
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="one")

    _put(client, headers, word, definition="two")
    _put(client, headers, word, definition="three")

    history = client.get(f"/api/v1/words/{word['id']}/history", headers=headers).json()
    assert history[0]["after_value"] == "three"


def test_a_first_value_records_no_before(client, headers):
    """"The model added this" and "the model replaced this" are different
    facts."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id)

    _put(client, headers, word, definition="a cat")

    history = client.get(f"/api/v1/words/{word['id']}/history", headers=headers).json()
    assert history[0]["before_value"] is None


def test_reading_another_accounts_history_is_refused(client, auth_headers):
    """The history of someone else's card describes their vocabulary."""
    alex = auth_headers()
    group_id = _group(client, alex)
    word = _ai_word(client, alex, group_id, definition="a cat")

    sam = auth_headers(username="sam", email="sam@example.com")

    assert client.get(f"/api/v1/words/{word['id']}/history", headers=sam).status_code in {403, 404}


def test_deleting_a_word_takes_its_history_with_it(client, headers, db_session):
    from app.infrastructure.repositories import SqlAlchemyWordRevisionRepository

    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, definition="a cat")
    _put(client, headers, word, definition="a small cat")

    client.delete(f"/api/v1/words/{word['id']}", headers=headers)

    assert SqlAlchemyWordRevisionRepository(db_session).list_for_word(word["id"]) == []


# --- Bulk editing ----------------------------------------------------------


def test_a_bulk_edit_sets_the_field_on_every_named_card(client, headers):
    group_id = _group(client, headers)
    first = _ai_word(client, headers, group_id, term="gato")
    second = _ai_word(client, headers, group_id, term="perro")

    resp = client.patch(
        "/api/v1/words/bulk",
        json={"word_ids": [first["id"], second["id"]], "cefr_level": "B1"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2
    assert client.get(f"/api/v1/words/{first['id']}", headers=headers).json()["cefr_level"] == "B1"


def test_a_field_left_out_of_a_bulk_edit_is_not_cleared(client, headers):
    """A bulk form that omitted a field must not wipe it."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, cefr_level="A2", part_of_speech="noun")

    client.patch(
        "/api/v1/words/bulk", json={"word_ids": [word["id"]], "cefr_level": "B1"}, headers=headers
    )

    fetched = client.get(f"/api/v1/words/{word['id']}", headers=headers).json()
    assert fetched["part_of_speech"] == "noun"


def test_another_accounts_ids_are_skipped_and_reported(client, auth_headers):
    """One bad id in a list of forty should not discard the other thirty-nine,
    and a bulk edit that quietly did less than asked is worse than one that
    says so."""
    alex = auth_headers()
    group_id = _group(client, alex)
    mine = _ai_word(client, alex, group_id)

    sam = auth_headers(username="sam", email="sam@example.com")
    sam_group = _group(client, sam)
    theirs = _ai_word(client, sam, sam_group)

    resp = client.patch(
        "/api/v1/words/bulk",
        json={"word_ids": [mine["id"], theirs["id"]], "cefr_level": "C1"},
        headers=alex,
    )

    assert resp.json()["updated"] == 1
    assert resp.json()["skipped"] == [theirs["id"]]


def test_a_bulk_edit_is_recorded_as_bulk_not_as_an_ordinary_edit(client, headers):
    """"I set the level on forty cards" is a different degree of attention from
    "I changed this card"."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, cefr_level="A1")

    client.patch(
        "/api/v1/words/bulk", json={"word_ids": [word["id"]], "cefr_level": "B2"}, headers=headers
    )

    history = client.get(f"/api/v1/words/{word['id']}/history", headers=headers).json()
    assert history[0]["source"] == "bulk"


def test_a_bulk_edit_that_changes_nothing_updates_nothing(client, headers):
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, cefr_level="B1")

    resp = client.patch(
        "/api/v1/words/bulk", json={"word_ids": [word["id"]], "cefr_level": "B1"}, headers=headers
    )

    assert resp.json()["updated"] == 0


def test_a_bulk_edit_cannot_overwrite_terms(client, headers):
    """Excluded on purpose: a control that could overwrite forty terms with one
    value is a mistake waiting to be made irreversibly."""
    group_id = _group(client, headers)
    word = _ai_word(client, headers, group_id, term="gato")

    client.patch(
        "/api/v1/words/bulk",
        json={"word_ids": [word["id"]], "term": "perro", "cefr_level": "B1"},
        headers=headers,
    )

    assert client.get(f"/api/v1/words/{word['id']}", headers=headers).json()["term"] == "gato"


def test_an_empty_bulk_request_is_rejected(client, headers):
    assert client.patch(
        "/api/v1/words/bulk", json={"word_ids": [], "cefr_level": "B1"}, headers=headers
    ).status_code == 422
