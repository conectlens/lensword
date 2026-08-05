"""Sync status, export and diagnostics (issue #91).

Three endpoints, each answering a question someone actually asks: *is it
working?*, *can I get my work out?*, and *what do I send to support?*

The middle one returns the user's data unredacted, because it is theirs. The
last one redacts it, because a bundle travels.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SyncOperationRepo
from app.api.schemas.sync import (
    DiagnosticBundleResponse,
    DiagnosticEntry,
    SyncHealthResponse,
    UnsyncedExportResponse,
    UnsyncedOperationExport,
)
from app.domain.services.sync_health import ConnectivityMode, SyncHealth, redact
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])

REDACTION_NOTE = (
    "Vocabulary, clipboard contents and credentials are removed. Operation "
    "identifiers, error classes and payload shape are retained so a failure "
    "can be diagnosed without disclosing what was being learned."
)


def _health(repo, user_id: int, connectivity: ConnectivityMode) -> SyncHealth:
    counts = repo.counts_by_status(user_id)
    return SyncHealth(
        last_synced_at=repo.last_applied_at(user_id),
        pending_count=counts.get("pending", 0),
        conflict_count=counts.get("conflict", 0),
        quarantined_count=counts.get("quarantined", 0),
        connectivity=connectivity,
    )


def _to_response(health: SyncHealth) -> SyncHealthResponse:
    return SyncHealthResponse(
        last_synced_at=health.last_synced_at,
        pending_count=health.pending_count,
        conflict_count=health.conflict_count,
        quarantined_count=health.quarantined_count,
        connectivity=health.connectivity,
        needs_attention=health.needs_attention,
    )


@router.get("/health", response_model=SyncHealthResponse)
def sync_health(
    current_user: CurrentUser,
    repo: SyncOperationRepo,
    # Reported by the client rather than inferred: a server reachable from the
    # data centre says nothing about a laptop on a train, and guessing produces
    # a status screen that contradicts what the user can see.
    connectivity: ConnectivityMode = Query(ConnectivityMode.ONLINE),
) -> SyncHealthResponse:
    return _to_response(_health(repo, current_user.id, connectivity))


@router.get("/export", response_model=UnsyncedExportResponse)
def export_unsynced(current_user: CurrentUser, repo: SyncOperationRepo) -> UnsyncedExportResponse:
    """Everything that has not reconciled, with payloads intact.

    Not redacted. This is the user's own work being handed back to them, and
    the point is that something done offline is recoverable even if it never
    syncs — a redacted export would be worthless for that.
    """
    operations = [
        *repo.list_by_status(current_user.id, "pending"),
        *repo.list_by_status(current_user.id, "conflict"),
        *repo.list_by_status(current_user.id, "quarantined"),
    ]
    return UnsyncedExportResponse(
        operations=[
            UnsyncedOperationExport(
                operation_id=o.operation_id,
                entity_type=o.entity_type,
                operation=o.operation,
                payload=o.payload,
                status=o.status,
                conflict_reason=o.conflict_reason,
                created_at=o.created_at,
            )
            for o in operations
        ],
        exported_at=utcnow(),
    )


@router.get("/diagnostics", response_model=DiagnosticBundleResponse)
def diagnostic_bundle(
    current_user: CurrentUser,
    repo: SyncOperationRepo,
    connectivity: ConnectivityMode = Query(ConnectivityMode.ONLINE),
) -> DiagnosticBundleResponse:
    """A bundle safe to send to support.

    Redacted by default and with no opt-out: a switch to include contents
    would be enabled by whoever is most frustrated, which is exactly the
    person least placed to judge the consequence.
    """
    entries = [
        *repo.list_by_status(current_user.id, "conflict"),
        *repo.list_by_status(current_user.id, "quarantined"),
        *repo.list_by_status(current_user.id, "pending"),
    ]
    return DiagnosticBundleResponse(
        generated_at=utcnow(),
        health=_to_response(_health(repo, current_user.id, connectivity)),
        entries=[
            DiagnosticEntry(
                operation_id=o.operation_id,
                entity_type=o.entity_type,
                operation=o.operation,
                status=o.status,
                attempts=o.attempts,
                error_class=o.error_class,
                payload_shape=redact(o.payload or {}),
                created_at=o.created_at,
            )
            for o in entries
        ],
        redaction_note=REDACTION_NOTE,
    )
