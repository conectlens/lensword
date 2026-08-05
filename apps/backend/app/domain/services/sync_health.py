"""Making synchronisation legible, and keeping one bad operation from
blocking the rest (issue #91).

Two ideas here, and the second is the one that matters.

*Legibility* is a summary: when sync last succeeded, how much is waiting, how
much is stuck. Cheap, and the difference between "it's broken" and a support
conversation that can start.

*Quarantine* is the property the issue actually names in its verification — a
forced permanent failure must not block later valid mutations. Without it a
single poison operation at the head of the queue stops every subsequent one
forever, and the user's only recourse is to reinstall. So an operation that
has failed enough times is set aside, and the queue moves on without it.

Nothing here logs vocabulary, clipboard contents or tokens. Diagnostics name
operation ids and error classes, which is what a support conversation needs
and is also all it is entitled to.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

# After this many failures an operation is quarantined rather than retried
# forever. Five is enough to ride out a token refresh or a deploy, and few
# enough that a genuinely poisoned operation is set aside the same day.
MAX_ATTEMPTS = 5

# Backoff between retries, capped. Uncapped exponential backoff on a mobile
# client reaches "next Tuesday" surprisingly fast, at which point the user
# concludes sync is broken and they are not wrong.
BASE_BACKOFF = timedelta(seconds=30)
MAX_BACKOFF = timedelta(minutes=30)
# Doublings needed to pass MAX_BACKOFF from BASE_BACKOFF. Beyond this the
# result is clamped anyway, so the exponent is capped here to keep the
# arithmetic in range.
_MAX_BACKOFF_STEPS = 16


class ConnectivityMode(str, Enum):
    """What the client believes about the server, in its own words.

    Reported by the client rather than inferred from request timing: a server
    that is reachable from the data centre says nothing about a laptop on a
    train, and guessing produces a status screen that contradicts what the
    user can see.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    # Reachable but refusing work — a deploy, a rate limit, an expired token.
    # Distinguished from offline because the remedies differ.
    DEGRADED = "degraded"


class SyncErrorClass(str, Enum):
    """Why an operation failed, at the granularity support needs.

    Deliberately coarse. A class is safe to log and to put in a diagnostic
    bundle; the underlying message may quote the payload, which is the user's
    vocabulary.
    """

    NETWORK = "network"
    AUTHENTICATION = "authentication"
    CONFLICT = "conflict"
    VALIDATION = "validation"
    SERVER = "server"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SyncHealth:
    """What a status screen shows."""

    last_synced_at: datetime | None
    pending_count: int
    conflict_count: int
    quarantined_count: int
    connectivity: ConnectivityMode

    @property
    def needs_attention(self) -> bool:
        """Whether to draw the user's eye.

        Pending work alone is not a problem — that is sync working. Conflicts
        and quarantined operations are, because neither resolves without a
        person.
        """
        return self.conflict_count > 0 or self.quarantined_count > 0


def backoff_for(attempts: int) -> timedelta:
    """Delay before the next attempt. Exponential, capped.

    Capped because uncapped exponential backoff reaches implausible delays in
    a handful of failures, and a client that will next try in four hours is
    indistinguishable from one that has given up.
    """
    if attempts <= 0:
        return timedelta(0)
    # The exponent is capped before it is used, not the result afterwards.
    # Computing BASE_BACKOFF * 2**49 first raises OverflowError, so a client
    # that had somehow accumulated that many attempts would crash on the way
    # to being told to wait half an hour.
    steps = min(attempts - 1, _MAX_BACKOFF_STEPS)
    return min(BASE_BACKOFF * (2**steps), MAX_BACKOFF)


def should_quarantine(attempts: int, error_class: SyncErrorClass) -> bool:
    """Whether to stop retrying and set this operation aside.

    Validation failures are quarantined immediately: the payload is malformed
    and will be just as malformed on the ninth attempt, so retrying only
    delays the point at which someone is told. Everything else gets its
    attempts, because networks and tokens recover.

    Conflicts are never quarantined — they are not failures. They already have
    a resolution path (#90) and are counted separately.
    """
    if error_class is SyncErrorClass.CONFLICT:
        return False
    if error_class is SyncErrorClass.VALIDATION:
        return True
    return attempts >= MAX_ATTEMPTS


# Payload keys that carry what the user is learning or typing. A diagnostic
# bundle exists to identify *which* operation failed and *why*, never what was
# in it — so these are dropped rather than truncated or hashed, both of which
# invite someone to try to recover them.
CONTENT_KEYS = frozenset(
    {
        "term",
        "translation",
        "translations",
        "definition",
        "example_sentence",
        "mnemonic",
        "text",
        "content",
        "notes",
        "synonyms",
        "antonyms",
        "topics",
        "collocations",
        "pronunciation",
        "clipboard",
        "captured_text",
    }
)

# Keys that carry credentials. Distinguished from content because the failure
# is worse and the rule is absolute: content is the user's to expose if they
# choose, a token is not theirs to leak at all.
SECRET_KEYS = frozenset(
    {"password", "token", "access_token", "secret", "authorization", "api_key", "secret_key"}
)


def redact(payload: dict) -> dict:
    """Strip content and secrets, keeping shape.

    Keys are kept with a placeholder rather than removed, because "this
    operation had a term and three translations" is genuinely useful for
    diagnosing a malformed payload, while the values are not. Matching is on
    the key name in lowercase, and nested dictionaries and lists are walked —
    a payload nested one level deeper is the obvious way for this to leak.
    """
    return _redact_value(payload)  # type: ignore[return-value]


def _redact_value(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SECRET_KEYS:
                cleaned[key] = "[secret]"
            elif lowered in CONTENT_KEYS:
                cleaned[key] = _describe(item)
            else:
                cleaned[key] = _redact_value(item)
        return cleaned
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _describe(value) -> str:
    """Say what was there without saying what it was."""
    if isinstance(value, list):
        return f"[{len(value)} redacted item(s)]"
    if isinstance(value, str):
        return f"[redacted {len(value)} chars]"
    return "[redacted]"
