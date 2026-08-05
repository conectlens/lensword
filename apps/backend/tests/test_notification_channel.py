import logging

from app.domain.entities import User
from app.domain.services.notification_channel import NotificationChannel
from app.domain.value_objects import UserRole
from app.infrastructure.notifications import LogNotificationChannel


def _user(**overrides) -> User:
    defaults = dict(
        id=1, username="alex", email="alex@example.com", hashed_password="x", role=UserRole.USER,
    )
    defaults.update(overrides)
    return User(**defaults)


class _FakeChannel:
    def __init__(self):
        self.calls = []

    def send(self, user, message, channel):
        self.calls.append((user, message, channel))


def test_fake_channel_satisfies_the_port_and_records_dispatch():
    fake: NotificationChannel = _FakeChannel()

    fake.send(_user(), "You have 5 words due for review", "push")

    assert len(fake.calls) == 1
    _, message, channel = fake.calls[0]
    assert message == "You have 5 words due for review"
    assert channel == "push"


def test_log_notification_channel_logs_user_message_and_channel(caplog):
    caplog.set_level(logging.INFO)
    channel: NotificationChannel = LogNotificationChannel()

    channel.send(_user(username="alex"), "You have 5 words due for review", "push")

    assert "alex" in caplog.text
    assert "You have 5 words due for review" in caplog.text
    assert "push" in caplog.text
