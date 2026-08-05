"""Sync status, export and diagnostics (issue #91)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.services.sync_health import ConnectivityMode


class SyncHealthResponse(BaseModel):
    # Null until something has actually synced. Distinct from "a long time
    # ago", which a zero timestamp would imply.
    last_synced_at: datetime | None
    pending_count: int
    conflict_count: int
    quarantined_count: int
    connectivity: ConnectivityMode
    # Whether to draw the user's eye. Pending work alone does not — that is
    # sync working, and flagging it trains people to ignore the indicator.
    needs_attention: bool


class UnsyncedOperationExport(BaseModel):
    """One unsynced operation, with its payload intact.

    This is the *user's own data* being handed back to them, so unlike the
    diagnostic bundle it is not redacted — the point is that work done offline
    is recoverable even if it never reconciles.
    """

    operation_id: str
    entity_type: str
    operation: str
    payload: dict
    status: str
    conflict_reason: str | None
    created_at: datetime


class UnsyncedExportResponse(BaseModel):
    operations: list[UnsyncedOperationExport]
    exported_at: datetime


class DiagnosticEntry(BaseModel):
    """One operation, described without its contents."""

    operation_id: str
    entity_type: str
    operation: str
    status: str
    attempts: int
    error_class: str | None
    # Redacted: keys kept, values replaced. "Had a term and three
    # translations" diagnoses a malformed payload; the values do not.
    payload_shape: dict
    created_at: datetime


class DiagnosticBundleResponse(BaseModel):
    generated_at: datetime
    health: SyncHealthResponse
    entries: list[DiagnosticEntry]
    # Stated in the bundle itself so anyone receiving one knows what it does
    # and does not contain, without having to trust the sender.
    redaction_note: str


class SyncOperationRequest(BaseModel):
    # Client-generated and stable across retries — the same id resubmitted
    # gets the same outcome back rather than being applied twice.
    operation_id: str = Field(min_length=1, max_length=64)
    entity_type: str = Field(pattern="^(word|review)$")
    # Null for a create: the server id does not exist until it is applied.
    entity_id: int | None = None
    operation: str = Field(pattern="^(create|update|delete|append)$")
    payload: dict = Field(default_factory=dict)
    # The revision this operation was made against. Required for a
    # reconcilable update; an append (a review) does not need one.
    base_revision: int | None = None


class SubmitSyncOperationsRequest(BaseModel):
    operations: list[SyncOperationRequest] = Field(min_length=1, max_length=200)


class SyncOperationResultResponse(BaseModel):
    operation_id: str
    status: str
    conflict_reason: str | None
    entity_id: int | None


class SubmitSyncOperationsResponse(BaseModel):
    results: list[SyncOperationResultResponse]


class ConflictResponse(BaseModel):
    """One operation that could not be reconciled, kept rather than dropped —
    a person decides, not the merge policy (issue #90)."""

    operation_id: str
    entity_type: str
    entity_id: int | None
    operation: str
    payload: dict
    base_revision: int | None
    conflict_reason: str | None
    created_at: datetime


class ConflictsResponse(BaseModel):
    conflicts: list[ConflictResponse]
