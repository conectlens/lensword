from app.domain.entities import User
from app.domain.services.badge_service import BadgeService
from app.domain.value_objects import UserRole


def _user(**overrides) -> User:
    defaults = dict(
        id=1, username="alex", email="alex@example.com", hashed_password="x",
        role=UserRole.USER, total_words_learned=0, longest_streak_days=0,
    )
    defaults.update(overrides)
    return User(**defaults)


def test_brand_new_user_has_earned_no_badges():
    earned = BadgeService.earned_badges(_user(), distinct_languages_studied=1)
    assert earned == []


def test_novice_linguist_earned_at_10_words():
    earned = BadgeService.earned_badges(_user(total_words_learned=10), distinct_languages_studied=1)
    codes = {b.code for b in earned}
    assert "novice_linguist" in codes
    assert "word_explorer" not in codes


def test_word_explorer_earned_at_100_words():
    earned = BadgeService.earned_badges(_user(total_words_learned=100), distinct_languages_studied=1)
    codes = {b.code for b in earned}
    assert {"novice_linguist", "word_explorer"} <= codes


def test_language_master_requires_1000_words():
    earned = BadgeService.earned_badges(_user(total_words_learned=999), distinct_languages_studied=1)
    assert "language_master" not in {b.code for b in earned}

    earned = BadgeService.earned_badges(_user(total_words_learned=1000), distinct_languages_studied=1)
    assert "language_master" in {b.code for b in earned}


def test_polyglot_prodigy_requires_three_languages():
    earned = BadgeService.earned_badges(_user(), distinct_languages_studied=2)
    assert "polyglot_prodigy" not in {b.code for b in earned}

    earned = BadgeService.earned_badges(_user(), distinct_languages_studied=3)
    assert "polyglot_prodigy" in {b.code for b in earned}


def test_streak_keeper_requires_seven_day_streak():
    earned = BadgeService.earned_badges(_user(longest_streak_days=6), distinct_languages_studied=1)
    assert "streak_keeper" not in {b.code for b in earned}

    earned = BadgeService.earned_badges(_user(longest_streak_days=7), distinct_languages_studied=1)
    assert "streak_keeper" in {b.code for b in earned}


def test_all_badges_returns_full_catalog_regardless_of_user():
    assert len(BadgeService.all_badges()) == 5
