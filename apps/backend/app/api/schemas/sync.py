"""Sync status, export and diagnostics (issue #91)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

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
