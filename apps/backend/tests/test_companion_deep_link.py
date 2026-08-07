import pytest

from app.domain.services.companion_deep_link import companion_notification_deep_link


def test_no_link_when_companion_disabled():
    assert companion_notification_deep_link(False) is None
    assert companion_notification_deep_link(False, session_id="s1") is None


def test_prompt_link_when_enabled_without_a_session():
    assert companion_notification_deep_link(True) == "lensword://prompt/daily_check_in"
    assert (
        companion_notification_deep_link(True, prompt="review_weakness")
        == "lensword://prompt/review_weakness"
    )


def test_session_link_wins_over_prompt():
    assert companion_notification_deep_link(True, session_id="abc123") == "lensword://session/abc123"


def test_unknown_prompt_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        companion_notification_deep_link(True, prompt="not_a_real_prompt")
