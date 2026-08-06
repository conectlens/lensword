import { describe, expect, it, vi, beforeEach } from 'vitest'

import {
  enqueue,
  isNetworkError,
  loadQueuedOperations,
  queueableRequest,
  queueLength,
  replayQueue,
} from './offlineQueue'
import { syncApi, ApiRequestError } from './api'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return {
    ...actual,
    syncApi: { submitOperations: vi.fn(), conflicts: vi.fn() },
  }
})

const submitOperations = vi.mocked(syncApi.submitOperations)

function wordUpdate(overrides: Partial<Parameters<typeof enqueue>[0]> = {}) {
  return {
    entity_type: 'word' as const,
    entity_id: 42,
    operation: 'update' as const,
    payload: { term: 'hola' },
    base_revision: 3,
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  submitOperations.mockReset()
})

describe('isNetworkError', () => {
  it('is true for a genuine fetch failure', () => {
    expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(true)
  })

  it('is false for an HTTP error response', () => {
    expect(isNetworkError(new ApiRequestError(409, 'conflict'))).toBe(false)
  })
})

describe('enqueue', () => {
  it('assigns a stable operation id and persists across the module', () => {
    const queued = enqueue(wordUpdate())
    expect(queued.operation_id).toBeTruthy()
    expect(queueLength()).toBe(1)
    expect(loadQueuedOperations()[0].operation_id).toBe(queued.operation_id)
  })

  it('each enqueued operation gets its own id', () => {
    const a = enqueue(wordUpdate())
    const b = enqueue(wordUpdate({ entity_id: 43 }))
    expect(a.operation_id).not.toBe(b.operation_id)
    expect(queueLength()).toBe(2)
  })
})

describe('queueableRequest', () => {
  it('returns the real result and never queues when the call succeeds', async () => {
    const result = await queueableRequest(
      async () => 'ok',
      () => wordUpdate(),
    )
    expect(result).toBe('ok')
    expect(queueLength()).toBe(0)
  })

  it('queues and returns undefined on a network failure', async () => {
    const result = await queueableRequest(
      async () => {
        throw new TypeError('Failed to fetch')
      },
      () => wordUpdate(),
    )
    expect(result).toBeUndefined()
    expect(queueLength()).toBe(1)
  })

  it('rethrows and does not queue an HTTP error response', async () => {
    await expect(
      queueableRequest(
        async () => {
          throw new ApiRequestError(422, 'invalid')
        },
        () => wordUpdate(),
      ),
    ).rejects.toBeInstanceOf(ApiRequestError)
    expect(queueLength()).toBe(0)
  })
})

describe('replayQueue', () => {
  it('does nothing when the queue is empty', async () => {
    const result = await replayQueue()
    expect(result).toEqual({ applied: 0, conflicts: 0 })
    expect(submitOperations).not.toHaveBeenCalled()
  })

  it('removes an applied operation from the queue', async () => {
    const queued = enqueue(wordUpdate())
    submitOperations.mockResolvedValue([
      { operation_id: queued.operation_id, status: 'applied', conflict_reason: null, entity_id: 42 },
    ])

    const result = await replayQueue()

    expect(result).toEqual({ applied: 1, conflicts: 0 })
    expect(queueLength()).toBe(0)
  })

  it('removes a conflicted operation too — it is a settled outcome, not a retry candidate', async () => {
    const queued = enqueue(wordUpdate())
    submitOperations.mockResolvedValue([
      { operation_id: queued.operation_id, status: 'conflict', conflict_reason: 'stale revision', entity_id: 42 },
    ])

    const result = await replayQueue()

    expect(result).toEqual({ applied: 0, conflicts: 1 })
    expect(queueLength()).toBe(0)
  })

  it('leaves the queue untouched when submission itself fails (still offline)', async () => {
    enqueue(wordUpdate())
    submitOperations.mockRejectedValue(new TypeError('Failed to fetch'))

    const result = await replayQueue()

    expect(result).toEqual({ applied: 0, conflicts: 0 })
    expect(queueLength()).toBe(1)
  })

  it('only removes operations the server actually settled, keeping the rest queued', async () => {
    const first = enqueue(wordUpdate({ entity_id: 1 }))
    const second = enqueue(wordUpdate({ entity_id: 2 }))
    submitOperations.mockResolvedValue([
      { operation_id: first.operation_id, status: 'applied', conflict_reason: null, entity_id: 1 },
      // second not present in the response — server dropped it somehow
    ])

    await replayQueue()

    expect(loadQueuedOperations().map((op) => op.operation_id)).toEqual([second.operation_id])
  })
})
