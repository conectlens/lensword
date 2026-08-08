"""Bring-Your-Own-Key AI credential schemas — the user-facing analogue of
app/api/schemas/ai_settings.py's admin-only shapes, with the same "never
echo a secret back" posture.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UserAICredentialSummary(BaseModel):
    """One configured provider, reported without ever including the secret
    itself. `details` carries whichever non-secret fields that provider's
    CredentialSchema.public_fields names (Vertex's project_id/location);
    empty for a provider with nothing non-secret to show (Gemini/OpenAI —
    an api_key has no non-secret part)."""

    provider: str
    details: dict[str, str]
    created_at: datetime
    updated_at: datetime
