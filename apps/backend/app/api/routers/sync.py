"""Sync status, export and diagnostics (issue #91).

Three endpoints, each answering a question someone actually asks: *is it
working?*, *can I get my work out?*, and *what do I send to support?*

The middle one returns the user's data unredacted, because it is theirs. The
last one redacts it, because a bundle travels.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import (
    CurrentUser,
    GroupRepo,
    MistakeEventRepo,
    RecallSettingsRepo,
    ReviewSessionRepo,
    SyncOperationRepo,
    WordRepo,
)
from app.api.schemas.sync import (
    ConflictResponse,
    ConflictsResponse,
    DiagnosticBundleResponse,
    DiagnosticEntry,
    SubmitSyncOperationsRequest,
    SubmitSyncOperationsResponse,
    SyncHealthResponse,
    SyncOperationResultResponse,
    UnsyncedExportResponse,
    UnsyncedOperationExport,
)
from app.application.use_cases.review import SubmitAnswerUseCase
from app.application.use_cases.sync import SubmitSyncOperationsUseCase, SyncOperationInput
from app.domain.services.spaced_repetition import FSRSScheduler, SpacedRepetitionScheduler
from app.domain.services.sync_health import ConnectivityMode, SyncHealth, redact
from app.domain.value_objects import utcnow

_scheduler = SpacedRepetitionScheduler()
_fsrs_scheduler = FSRSScheduler()

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


@router.post("/operations", response_model=SubmitSyncOperationsResponse)
def submit_operations(
    payload: SubmitSyncOperationsRequest,
    current_user: CurrentUser,
    sync_repo: SyncOperationRepo,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    session_repo: ReviewSessionRepo,
    settings_repo: RecallSettingsRepo,
    mistake_repo: MistakeEventRepo,
) -> SubmitSyncOperationsResponse:
    """Reconcile a batch of offline mutations (issue #90).

    Always 200: an individual operation's outcome is `applied` or
    `conflict`, not an HTTP error, because a stale edit is an expected
    outcome of working offline, not a fault. Every operation submitted gets
    an outcome — none are silently dropped, including ones this account
    does not own, which come back as a conflict for that operation rather
    than a fault that discards the rest of the batch.
    """
    settings = settings_repo.get_by_user(current_user.id)
    selected_scheduler = _fsrs_scheduler if settings and settings.scheduler == "fsrs" else _scheduler
    review_use_case = SubmitAnswerUseCase(session_repo, word_repo, selected_scheduler, mistake_repo)

    use_case = SubmitSyncOperationsUseCase(sync_repo, word_repo, group_repo, review_use_case)
    outcomes = use_case.execute(
        current_user.id,
        [
            SyncOperationInput(
                operation_id=op.operation_id,
                entity_type=op.entity_type,
                entity_id=op.entity_id,
                operation=op.operation,
                payload=op.payload,
                base_revision=op.base_revision,
            )
            for op in payload.operations
        ],
    )
    return SubmitSyncOperationsResponse(
        results=[
            SyncOperationResultResponse(
                operation_id=o.operation_id,
                status=o.status,
                conflict_reason=o.conflict_reason,
                entity_id=o.entity_id,
            )
            for o in outcomes
        ]
    )


@router.get("/conflicts", response_model=ConflictsResponse)
def list_conflicts(current_user: CurrentUser, repo: SyncOperationRepo) -> ConflictsResponse:
    """Operations that could not be reconciled, surfaced for a person to
    resolve — never silently discarded (issue #90)."""
    conflicts = repo.list_conflicts(current_user.id)
    return ConflictsResponse(
        conflicts=[
            ConflictResponse(
                operation_id=c.operation_id,
                entity_type=c.entity_type,
                entity_id=c.entity_id,
                operation=c.operation,
                payload=c.payload,
                base_revision=c.base_revision,
                conflict_reason=c.conflict_reason,
                created_at=c.created_at,
            )
            for c in conflicts
        ]
    )
