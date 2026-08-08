"""Application-level authenticated encryption for Bring-Your-Own-Key AI
credentials.

One master key (`Settings.ai_credential_encryption_key`), symmetric
authenticated encryption (`cryptography.fernet.Fernet` — AES-128-CBC + HMAC,
key rotation and timestamp metadata built in), no external service to run.
This matches the project's self-hosted-first posture (SQLite by default, a
zero-dependency CLI, a single Docker/Render deploy) explicitly instead of
HashiCorp Vault or a cloud KMS: those solve a real problem, but it is not
this project's problem, and both would turn "a self-hosted Docker Compose
stack" into "a self-hosted Docker Compose stack plus a second service to
run, back up, and keep available or every BYOK credential becomes
unreadable."

Provider-agnostic on purpose: this module encrypts and decrypts opaque JSON
payloads and knows nothing about what "gemini" or "vertex" means — that
split is what lets app.domain.services.ai_credentials add a new provider
without this module changing at all.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CredentialEncryptionNotConfiguredError(RuntimeError):
    """Raised when a BYOK credential must be encrypted or decrypted but no
    AI_CREDENTIAL_ENCRYPTION_KEY is configured.

    Deliberately loud rather than a silent no-op: storing a credential
    unencrypted "for now" because a key was never set is exactly the kind
    of failure mode that must stop the operation, not degrade it quietly —
    matching this codebase's existing "fail at startup/at the operation,
    not at generation" posture for every other AI configuration error (see
    app.infrastructure.ai_providers.factory.build_ai_provider's own
    docstring).
    """

    def __init__(self) -> None:
        super().__init__(
            "AI_CREDENTIAL_ENCRYPTION_KEY is not configured — Bring-Your-Own-Key AI "
            "credentials cannot be stored or read until it is set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )


class CredentialDecryptionError(RuntimeError):
    """Raised when a stored blob cannot be decrypted with the configured
    key — a wrong/rotated AI_CREDENTIAL_ENCRYPTION_KEY, or a blob that has
    been corrupted or tampered with (Fernet is authenticated: a modified
    ciphertext fails to decrypt rather than silently returning garbage).
    Never includes the raw token or key material in its message."""

    def __init__(self) -> None:
        super().__init__("Stored AI credential could not be decrypted")


@lru_cache
def _fernet(key: str) -> Fernet:
    """Cached per key value (there is normally exactly one, the configured
    master key) — Fernet's own constructor does non-trivial base64/key
    validation, no need to repeat it on every encrypt/decrypt call in a
    request-heavy path."""
    return Fernet(key.encode("utf-8"))


def _require_key(encryption_key: str | None) -> Fernet:
    if not encryption_key:
        raise CredentialEncryptionNotConfiguredError()
    try:
        return _fernet(encryption_key)
    except (ValueError, TypeError) as exc:
        # Fernet() raises on a key that isn't valid urlsafe-base64 32 bytes —
        # a misconfigured (not merely missing) key. Treated the same as
        # "not configured": either way, nothing can be encrypted or
        # decrypted with it, and the fix is the same (set a real key).
        logger.error("AI_CREDENTIAL_ENCRYPTION_KEY is set but not a valid Fernet key: %s", exc)
        raise CredentialEncryptionNotConfiguredError() from exc


def encrypt_credential(payload: dict, *, encryption_key: str | None) -> bytes:
    """Serialize and encrypt a validated credential payload.

    Callers pass the already-validated payload (see
    app.domain.services.ai_credentials.CredentialSchema.validate) — this
    function does not itself judge whether the payload is a well-formed
    credential, only that it is JSON-serializable, since that is all
    encryption needs to be true.
    """
    fernet = _require_key(encryption_key)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return fernet.encrypt(raw)


def decrypt_credential(blob: bytes, *, encryption_key: str | None) -> dict:
    """Decrypt and parse a stored credential blob back into its payload.

    Raises CredentialDecryptionError (never InvalidToken or a raw
    json.JSONDecodeError) on any failure — the caller must not have to
    know which of "wrong key", "corrupted row", or "not actually JSON"
    happened, only that the credential is currently unusable and, unlike
    every other AIProviderUnavailableError case elsewhere in this codebase,
    this one cannot be fixed by retrying.
    """
    fernet = _require_key(encryption_key)
    try:
        raw = fernet.decrypt(blob)
    except InvalidToken as exc:
        logger.warning("AI credential blob failed to decrypt (wrong key or corrupted row)")
        raise CredentialDecryptionError() from exc
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("AI credential blob decrypted but was not valid JSON")
        raise CredentialDecryptionError() from exc
    if not isinstance(payload, dict):
        raise CredentialDecryptionError()
    return payload
