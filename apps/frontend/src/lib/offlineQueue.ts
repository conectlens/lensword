/**
 * Client-side offline mutation queue (issue #218), on top of the server's
 * own reconciliation contract (issue #90: `POST /api/v1/sync/operations`,
 * `SyncMergePolicy`, a `revision` on every word).
 *
 * Scoped to exactly the two entity types the backend can reconcile — `word`
 * and `review` — not a general-purpose request queue. Queuing a mutation
 * the server cannot replay would just be a doomed retry with extra steps.
 *
 * Storage is `localStorage` rather than IndexedDB: a queue entry is a small
 * JSON object and there are, in practice, a handful of them at a time
 * (someone editing vocabulary offline, not importing a spreadsheet) — the
 * synchronous API is simpler and there is no meaningful volume here to
 * justify IndexedDB's asynchronous one.
 */
import { syncApi, ApiRequestError } from './api'
import type { QueuedOperation, SyncEntityType, SyncOperationKind } from './types'

const STORAGE_KEY = 'lensword.offline-queue'

// The backend's own cap on one batch (SubmitSyncOperationsRequest.operations,
// max_length=200). Replayed in chunks of this size rather than raised as an
// error, since the queue can legitimately grow past it during a long outage.
const MAX_BATCH_SIZE = 200

function loadQueue(): QueuedOperation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    // Corrupted storage (a manual edit, a browser bug) is not a reason to
    // crash every page that touches the queue — treat it as empty rather
    // than throwing, the same way a missing file means "unconfigured"
    // elsewhere in this codebase.
    return []
  }
}

function saveQueue(queue: QueuedOperation[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(queue))
  // Same-tab listeners (a status badge, a settings card) cannot hear
  // `storage`, which only fires in *other* tabs — this is the same-tab
  // equivalent, dispatched right after every write so a listener never has
  // to poll to notice a change it caused itself.
  window.dispatchEvent(new CustomEvent(QUEUE_CHANGED_EVENT))
}

/** Fired on every enqueue/replay outcome, `detail` omitted deliberately —
 *  listeners re-read `queueLength()`/`loadQueuedOperations()` themselves
 *  rather than trusting a payload that could drift from what is actually
 *  stored. */
export const QUEUE_CHANGED_EVENT = 'lensword:offline-queue-changed'

export function queueLength(): number {
  return loadQueue().length
}

export function loadQueuedOperations(): QueuedOperation[] {
  return loadQueue()
}

/** True for a genuine network failure (offline, DNS failure, connection
 *  refused) — `fetch` itself rejects with this rather than resolving, which
 *  is exactly the case an HTTP error response (`ApiRequestError`, a real
 *  answer from a reachable server) is not. Queuing on an `ApiRequestError`
 *  would retry a request the server has already told us is invalid. */
export function isNetworkError(error: unknown): boolean {
  return !(error instanceof ApiRequestError)
}

export function enqueue(op: {
  entity_type: SyncEntityType
  entity_id: number | null
  operation: SyncOperationKind
  payload: Record<string, unknown>
  base_revision: number | null
}): QueuedOperation {
  const queued: QueuedOperation = {
    ...op,
    operation_id: crypto.randomUUID(),
    queued_at: new Date().toISOString(),
  }
  const queue = loadQueue()
  queue.push(queued)
  saveQueue(queue)
  return queued
}

/**
 * Runs `apiCall`. On a genuine network failure, queues `queueSpec` instead
 * of throwing, so an offline edit reads as a (locally) successful one to
 * the caller — an HTTP error response still throws normally, since that is
 * the server telling us the request itself is invalid, not that it is
 * unreachable.
 */
export async function queueableRequest<T>(
  apiCall: () => Promise<T>,
  queueSpec: () => {
    entity_type: SyncEntityType
    entity_id: number | null
    operation: SyncOperationKind
    payload: Record<string, unknown>
    base_revision: number | null
  },
): Promise<T | undefined> {
  try {
    return await apiCall()
  } catch (error) {
    if (!isNetworkError(error)) throw error
    enqueue(queueSpec())
    return undefined
  }
}

/**
 * Submits every queued operation, in chunks bounded by the server's own
 * batch limit. An operation is removed from the local queue once the
 * server has recorded *any* outcome for it — applied or conflict — since
 * both are durable decisions the server will return unchanged on a retry
 * (the same operation_id resubmitted gets the same recorded outcome back,
 * never re-applied); a conflict is not a reason to keep retrying locally,
 * it is a reason to surface it via `GET /api/v1/sync/conflicts` instead.
 * An operation whose submission itself fails (still offline) is left in
 * the queue for the next attempt.
 */
export async function replayQueue(): Promise<{ applied: number; conflicts: number }> {
  const queue = loadQueue()
  if (queue.length === 0) return { applied: 0, conflicts: 0 }

  let applied = 0
  let conflicts = 0
  let remaining = queue

  for (let start = 0; start < queue.length; start += MAX_BATCH_SIZE) {
    const batch = queue.slice(start, start + MAX_BATCH_SIZE)
    let results
    try {
      results = await syncApi.submitOperations(batch)
    } catch {
      // Still offline, or the server itself is unreachable — stop here and
      // leave this batch and everything after it queued for next time.
      break
    }
    const settledIds = new Set(results.map((r) => r.operation_id))
    for (const result of results) {
      if (result.status === 'applied') applied += 1
      else conflicts += 1
    }
    remaining = remaining.filter((op) => !settledIds.has(op.operation_id))
  }

  saveQueue(remaining)
  return { applied, conflicts }
}
