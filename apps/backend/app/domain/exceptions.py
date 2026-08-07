"""Domain-level exceptions.

These carry business meaning and are translated to HTTP responses at the API
boundary (see app.api.deps / FastAPI exception handlers). Nothing in this
module knows about HTTP status codes.
"""


class DomainError(Exception):
    """Base class for all domain errors."""


class EntityNotFoundError(DomainError):
    def __init__(self, entity: str, entity_id: object):
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} '{entity_id}' was not found")


class DuplicateEmailError(DomainError):
    def __init__(self, email: str):
        self.email = email
        super().__init__(f"An account with email '{email}' already exists")


class DuplicateUsernameError(DomainError):
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"Username '{username}' is already taken")


class InvalidCredentialsError(DomainError):
    def __init__(self):
        super().__init__("Incorrect email or password")


class PermissionDeniedError(DomainError):
    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message)


class WordNotInGroupError(DomainError):
    def __init__(self, word_id: int, group_id: int):
        super().__init__(f"Word '{word_id}' does not belong to group '{group_id}'")


class InvalidPlacementError(DomainError):
    def __init__(self, message: str):
        super().__init__(message)


class SessionAlreadyCompletedError(DomainError):
    def __init__(self, session_id: int):
        super().__init__(f"Review session '{session_id}' has already been completed")


class NoWordsDueError(DomainError):
    def __init__(self):
        super().__init__("There are no words due for review right now")


class ValidationError(DomainError):
    def __init__(self, message: str):
        super().__init__(message)


class AIProviderNotConfiguredError(DomainError):
    """Raised when an AI-backed feature is asked for but no provider is
    configured. Deliberately a sibling of AIProviderUnavailableError rather
    than a subclass: 'switched off' is a settings state the caller should
    report calmly, while 'unavailable' is a transient fault worth retrying,
    and the two must stay distinguishable."""

    def __init__(self, message: str = "No AI provider is configured"):
        super().__init__(message)


class AIProviderUnavailableError(DomainError):
    """Raised by an AIProvider adapter when the configured backend can't be
    reached or returns something unusable — never let a raw transport
    exception (connection refused, timeout, mid-response drop) reach a
    caller directly.

    The default message is deliberately generic and operator-agnostic: it is
    surfaced verbatim to API clients, and the provider address may carry
    credentials (`str(httpx.URL)` does not mask userinfo, only `repr` does).
    Which backend failed, and why, belongs in the server log instead.
    """

    def __init__(self, message: str = "The AI provider is not reachable — try again shortly."):
        super().__init__(message)


class ConcurrentModificationError(DomainError):
    """Raised when a write targets a stale revision of an entity.

    The caller read an entity at revision N, another write already moved it
    to a later revision, and this write's WHERE-clause therefore matched no
    row. This is not "not found" (the row exists) and not a validation
    problem with the payload — it is a lost-update race the caller must
    re-read and retry, which is why it stays a distinct domain error rather
    than folding into EntityNotFoundError or ValidationError.
    """

    def __init__(self, entity: str, entity_id: object, expected_revision: int):
        self.entity = entity
        self.entity_id = entity_id
        self.expected_revision = expected_revision
        super().__init__(
            f"{entity} '{entity_id}' was not at the expected revision {expected_revision} "
            "— it was modified concurrently; re-read and retry"
        )


class NotificationExpiredError(DomainError):
    """An action was taken on a notification whose actions have lapsed.

    Distinct from "not found": the notification is real and belongs to the
    caller, it is simply too old to answer. The caller needs to tell those
    apart to decide whether to show an error or quietly drop a stale OS
    callback.
    """
