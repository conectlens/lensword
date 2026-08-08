"""Bring-Your-Own-Key AI credentials — a user's own Gemini/OpenAI/Vertex AI
key, for their own requests (see app.api.deps.get_ai_provider_for_user).
User-scoped (CurrentUser), not admin-only like app/api/routers/
ai_settings.py's deployment-wide equivalent — every user manages their own
credentials, no admin opt-in gate required.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, UserAICredentialRepo, rate_limit_ai_credential_write
from app.api.schemas.ai_credentials import UserAICredentialSummary
from app.config import Settings, get_settings
from app.domain.entities import UserAICredential
from app.domain.services.ai_credentials import PROVIDER_CREDENTIAL_SCHEMAS, CredentialValidationError
from app.domain.value_objects import utcnow
from app.infrastructure.credential_vault import (
    CredentialDecryptionError,
    CredentialEncryptionNotConfiguredError,
    decrypt_credential,
    encrypt_credential,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/me/ai-credentials", tags=["AI credentials"])


def _unknown_provider(provider: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            f"Unknown AI provider '{provider}' — supported values are: "
            f"{', '.join(sorted(PROVIDER_CREDENTIAL_SCHEMAS))}"
        ),
    )


def _to_summary(credential: UserAICredential, *, encryption_key: str | None) -> UserAICredentialSummary:
    schema = PROVIDER_CREDENTIAL_SCHEMAS.get(credential.provider)
    details: dict[str, str] = {}
    if schema is not None:
        try:
            payload = decrypt_credential(credential.encrypted_payload, encryption_key=encryption_key)
            details = {
                key: str(value) for key, value in schema.public_view(payload).items()
            }
        except (CredentialDecryptionError, CredentialEncryptionNotConfiguredError):
            # A row this account cannot currently decrypt (a rotated master
            # key, a misconfigured deploy) still names *which* provider is
            # configured and when it was last touched — that is worth
            # showing rather than hiding the whole row or 500ing the whole
            # list over one unreadable entry. What is not shown is
            # unaffected: this never touches the secret half of the
            # payload at all.
            logger.warning(
                "could not decrypt stored AI credential for user %s provider %s",
                credential.user_id, credential.provider,
            )
    return UserAICredentialSummary(
        provider=credential.provider,
        details=details,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.get("", response_model=list[UserAICredentialSummary])
def list_my_ai_credentials(
    current_user: CurrentUser,
    repo: UserAICredentialRepo,
    settings: Settings = Depends(get_settings),
) -> list[UserAICredentialSummary]:
    credentials = repo.list_for_user(current_user.id)
    return [_to_summary(credential, encryption_key=settings.ai_credential_encryption_key) for credential in credentials]


@router.put("/{provider}", response_model=UserAICredentialSummary)
def put_my_ai_credential(
    provider: str,
    payload: dict[str, str],
    current_user: CurrentUser,
    repo: UserAICredentialRepo,
    settings: Settings = Depends(get_settings),
    _rate_limited: None = Depends(rate_limit_ai_credential_write),
) -> UserAICredentialSummary:
    schema = PROVIDER_CREDENTIAL_SCHEMAS.get(provider)
    if schema is None:
        raise _unknown_provider(provider)

    try:
        schema.validate(payload)
    except CredentialValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    try:
        encrypted = encrypt_credential(dict(payload), encryption_key=settings.ai_credential_encryption_key)
    except CredentialEncryptionNotConfiguredError as exc:
        # A deploy that enables BYOK's API surface without configuring
        # AI_CREDENTIAL_ENCRYPTION_KEY is a server misconfiguration, not
        # something the submitting user did wrong — 503, not 422/400.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    now = utcnow()
    saved = repo.upsert(
        UserAICredential(
            user_id=current_user.id, provider=provider, encrypted_payload=encrypted, created_at=now, updated_at=now,
        )
    )
    return _to_summary(saved, encryption_key=settings.ai_credential_encryption_key)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_ai_credential(
    provider: str,
    current_user: CurrentUser,
    repo: UserAICredentialRepo,
    _rate_limited: None = Depends(rate_limit_ai_credential_write),
) -> None:
    if provider not in PROVIDER_CREDENTIAL_SCHEMAS:
        raise _unknown_provider(provider)
    removed = repo.delete(current_user.id, provider)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider} credential is configured for this account",
        )
