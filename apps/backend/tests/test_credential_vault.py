"""Tests for app.infrastructure.credential_vault — the Fernet
encrypt/decrypt layer behind Bring-Your-Own-Key AI credentials.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.infrastructure.credential_vault import (
    CredentialDecryptionError,
    CredentialEncryptionNotConfiguredError,
    decrypt_credential,
    encrypt_credential,
)


def _key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_encrypt_then_decrypt_round_trips_the_exact_payload():
    key = _key()
    payload = {"api_key": "sk-super-secret-value-123"}

    blob = encrypt_credential(payload, encryption_key=key)
    result = decrypt_credential(blob, encryption_key=key)

    assert result == payload


def test_a_multi_field_payload_round_trips_intact():
    key = _key()
    payload = {
        "service_account_json": '{"type": "service_account", "private_key": "abc"}',
        "project_id": "test-project",
        "location": "us-central1",
    }

    blob = encrypt_credential(payload, encryption_key=key)
    assert decrypt_credential(blob, encryption_key=key) == payload


def test_the_encrypted_blob_never_contains_the_plaintext_secret():
    key = _key()
    payload = {"api_key": "sk-a-very-distinctive-marker-value"}

    blob = encrypt_credential(payload, encryption_key=key)

    assert b"sk-a-very-distinctive-marker-value" not in blob


def test_decrypting_with_the_wrong_key_raises_a_decryption_error_not_the_raw_exception():
    payload = {"api_key": "sk-secret"}
    blob = encrypt_credential(payload, encryption_key=_key())

    with pytest.raises(CredentialDecryptionError):
        decrypt_credential(blob, encryption_key=_key())


def test_decrypting_a_tampered_blob_raises_a_decryption_error():
    """Fernet is authenticated — a modified ciphertext must fail closed,
    never decrypt into something that merely looks wrong."""
    key = _key()
    blob = bytearray(encrypt_credential({"api_key": "sk-secret"}, encryption_key=key))
    blob[-5] ^= 0xFF  # flip bits near the end (inside the HMAC tag)

    with pytest.raises(CredentialDecryptionError):
        decrypt_credential(bytes(blob), encryption_key=key)


def test_encrypting_without_a_configured_key_raises_a_clear_error():
    with pytest.raises(CredentialEncryptionNotConfiguredError):
        encrypt_credential({"api_key": "sk-secret"}, encryption_key=None)


def test_decrypting_without_a_configured_key_raises_a_clear_error():
    with pytest.raises(CredentialEncryptionNotConfiguredError):
        decrypt_credential(b"anything", encryption_key=None)


def test_a_malformed_encryption_key_string_raises_the_not_configured_error():
    """Distinguished from CredentialDecryptionError: a key that is not
    even valid Fernet key material is a configuration problem, the same
    class of error as no key at all — not a per-blob decryption failure."""
    with pytest.raises(CredentialEncryptionNotConfiguredError):
        encrypt_credential({"api_key": "sk-secret"}, encryption_key="not-a-real-fernet-key")


def test_encrypting_the_same_payload_twice_produces_different_ciphertext():
    """Fernet includes a random IV and timestamp per call — this is what
    makes the scheme semantically secure (equal plaintexts are not
    distinguishable from their ciphertext alone), and is worth pinning so
    a future "optimization" that reuses a nonce would be caught here."""
    key = _key()
    payload = {"api_key": "sk-secret"}

    assert encrypt_credential(payload, encryption_key=key) != encrypt_credential(payload, encryption_key=key)
