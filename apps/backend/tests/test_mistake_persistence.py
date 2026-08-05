"""Recording mistakes and serving the weakness profile (issue #134).

The aggregation logic is tested in `test_weakness_profile.py`; this covers the
half that touches the database — what gets written on a wrong answer, what
survives a word being deleted, and who is allowed to read it.
"""
from __future__ import annotations

import pytest

from app.domain.entities import Group, User, Word
from app.domain.value_objects import SupportedLanguage, UserRole
from app.infrastructure.repositories import (
    SqlAlchemyGroupRepository,
    SqlAlchemyMistakeEventRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)


@pytest.fixture()
def owner(db_session):
    return SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="alex", email="alex@example.com", hashed_password="x", role=UserRole.USER)
    )


@pytest.fixture()
def group(db_session, owner):
    return SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=owner.id, name="Spanish", target_language=SupportedLanguage.SPANISH)
    )


def _word(db_session, group, term: str) -> Word:
    return SqlAlchemyWordRepository(db_session).add(
        Word(id=None, group_id=group.id, term=term, target_language=SupportedLanguage.SPANISH,
             translations=["x"])
    )


# --- Recording -------------------------------------------------------------


def test_a_mistake_is_stored_and_read_back(db_session, owner, group):
    word = _word(db_session, group, "gato")
    repo = SqlAlchemyMistakeEventRepository(db_session)

    repo.record(user_id=owner.id, word_id=word.id, category="wrong_word", attempted_answer="perro")

    stored = repo.list_for_user(owner.id)
    assert len(stored) == 1
    assert stored[0].attempted_answer == "perro"
    assert stored[0].occurred_at is not None


def test_a_pathological_answer_is_truncated_rather_than_rejected(db_session, owner, group):
    """A review submission must not fail because someone pasted a novel into
    the answer box. The review is the user's actual work; the mistake record is
    bookkeeping beside it."""
    word = _word(db_session, group, "gato")
    repo = SqlAlchemyMistakeEventRepository(db_session)

    repo.record(user_id=owner.id, word_id=word.id, category="spelling", attempted_answer="x" * 5000)

    assert len(repo.list_for_user(owner.id)[0].attempted_answer) == 255


def test_one_learners_mistakes_are_not_visible_to_another(db_session, owner, group):
    other = SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="sam", email="sam@example.com", hashed_password="x", role=UserRole.USER)
    )
    word = _word(db_session, group, "gato")
    repo = SqlAlchemyMistakeEventRepository(db_session)
    repo.record(user_id=owner.id, word_id=word.id, category="spelling")

    assert repo.list_for_user(other.id) == []


def test_mistakes_come_back_newest_first(db_session, owner, group):
    from datetime import datetime

    word = _word(db_session, group, "gato")
    repo = SqlAlchemyMistakeEventRepository(db_session)
    repo.record(user_id=owner.id, word_id=word.id, category="spelling",
                occurred_at=datetime(2026, 1, 1, 9, 0))
    repo.record(user_id=owner.id, word_id=word.id, category="sense",
                occurred_at=datetime(2026, 6, 1, 9, 0))

    assert [row.category for row in repo.list_for_user(owner.id)] == ["sense", "spelling"]


# --- Deleting a word -------------------------------------------------------


def test_deleting_a_word_deletes_its_mistakes(db_session, owner, group):
    """Otherwise the row references a word that no longer exists — a foreign
    key violation on Postgres and a silently orphaned row on SQLite."""
    word = _word(db_session, group, "gato")
    repo = SqlAlchemyMistakeEventRepository(db_session)
    repo.record(user_id=owner.id, word_id=word.id, category="spelling")

    SqlAlchemyWordRepository(db_session).delete(word.id)

    assert repo.list_for_user(owner.id) == []


def test_deleting_the_confused_with_word_keeps_the_mistake(db_session, owner, group):
    """The mistake still happened. It degrades to a plain wrong-word error
    rather than being deleted along with a word it merely mentioned."""
    word = _word(db_session, group, "gato")
    other = _word(db_session, group, "gata")
    repo = SqlAlchemyMistakeEventRepository(db_session)
    repo.record(user_id=owner.id, word_id=word.id, category="wrong_word",
                confused_with_word_id=other.id)

    SqlAlchemyWordRepository(db_session).delete(other.id)

    remaining = repo.list_for_user(owner.id)
    assert len(remaining) == 1
    assert remaining[0].confused_with_word_id is None


def test_deleting_a_group_takes_its_words_mistakes_with_it(db_session, owner, group):
    word = _word(db_session, group, "gato")
    repo = SqlAlchemyMistakeEventRepository(db_session)
    repo.record(user_id=owner.id, word_id=word.id, category="spelling")

    SqlAlchemyGroupRepository(db_session).delete(group.id)

    assert repo.list_for_user(owner.id) == []


# --- Term lookup used to name a confusion ----------------------------------


def test_a_term_resolves_to_the_learners_own_word(db_session, owner, group):
    word = _word(db_session, group, "gato")

    assert SqlAlchemyWordRepository(db_session).find_id_by_term(owner.id, "gato") == word.id


def test_term_lookup_ignores_case_and_space(db_session, owner, group):
    """"Gato" and "gato" are the same word to a learner, and a confusion pair
    that depended on capitalisation would record typing rather than memory."""
    word = _word(db_session, group, "gato")

    assert SqlAlchemyWordRepository(db_session).find_id_by_term(owner.id, "  GATO ") == word.id


def test_term_lookup_does_not_cross_accounts(db_session, owner, group):
    """The lookup names a confusion between two words the learner studies.
    Reaching into another account's vocabulary would both leak its existence
    and invent a pair the learner could not have confused."""
    other = SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="sam", email="sam@example.com", hashed_password="x", role=UserRole.USER)
    )
    _word(db_session, group, "gato")

    assert SqlAlchemyWordRepository(db_session).find_id_by_term(other.id, "gato") is None


def test_an_unknown_term_resolves_to_nothing(db_session, owner, group):
    _word(db_session, group, "gato")

    assert SqlAlchemyWordRepository(db_session).find_id_by_term(owner.id, "quetzalcoatl") is None


def test_an_empty_term_is_not_looked_up(db_session, owner, group):
    _word(db_session, group, "gato")

    assert SqlAlchemyWordRepository(db_session).find_id_by_term(owner.id, "   ") is None
