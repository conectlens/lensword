/**
 * The collect → show → acknowledge loop (ROADMAP 3.2, issue #31).
 *
 * The ordering is the part worth pinning. Acknowledging before showing would
 * lose a notification whenever the shell dies mid-cycle; acknowledging ones
 * that were never shown does the same thing more quietly.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listPending = vi.fn()
const acknowledge = vi.fn()

vi.mock('./api', () => ({
  notificationsApi: {
    listPending: () => listPending(),
    acknowledge: (ids: number[]) => acknowledge(ids),
  },
}))

const { drainOnce, isDesktopShell } = await import('./desktopNotifications')

function pending(...messages: string[]) {
  return {
    notifications: messages.map((message, index) => ({
      id: index + 1,
      message,
      created_at: '2026-08-02T09:00:00',
    })),
    has_more: false,
  }
}

beforeEach(() => {
  listPending.mockReset()
  acknowledge.mockReset()
  acknowledge.mockResolvedValue({ acknowledged: 0 })
})

describe('drainOnce', () => {
  it('shows every pending notification and acknowledges them together', async () => {
    listPending.mockResolvedValue(pending('5 words are due', '2 more'))
    const show = vi.fn().mockResolvedValue(undefined)

    const shown = await drainOnce(show)

    expect(shown).toBe(2)
    expect(show).toHaveBeenCalledTimes(2)
    expect(show).toHaveBeenCalledWith('LensWord', '5 words are due')
    expect(acknowledge).toHaveBeenCalledWith([1, 2])
  })

  it('acknowledges only after the toast is raised', async () => {
    const order: string[] = []
    listPending.mockResolvedValue(pending('due'))
    acknowledge.mockImplementation(async () => {
      order.push('ack')
      return { acknowledged: 1 }
    })
    const show = vi.fn().mockImplementation(async () => {
      order.push('show')
    })

    await drainOnce(show)

    expect(order).toEqual(['show', 'ack'])
  })

  it('does not acknowledge anything when nothing could be shown', async () => {
    listPending.mockResolvedValue(pending('due'))
    const show = vi.fn().mockRejectedValue(new Error('no notification service'))

    const shown = await drainOnce(show)

    expect(shown).toBe(0)
    expect(acknowledge).not.toHaveBeenCalled()
  })

  it('acknowledges only what was actually shown when showing fails partway', async () => {
    listPending.mockResolvedValue(pending('first', 'second', 'third'))
    const show = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('service went away'))

    const shown = await drainOnce(show)

    expect(shown).toBe(1)
    // Not [1, 2, 3]: the unshown two stay pending and are retried, rather than
    // being marked delivered because their neighbour succeeded.
    expect(acknowledge).toHaveBeenCalledWith([1])
  })

  it('makes no acknowledge call when the outbox is empty', async () => {
    listPending.mockResolvedValue({ notifications: [], has_more: false })
    const show = vi.fn()

    expect(await drainOnce(show)).toBe(0)
    expect(show).not.toHaveBeenCalled()
    expect(acknowledge).not.toHaveBeenCalled()
  })
})

describe('isDesktopShell', () => {
  it('is false in a plain browser, so the web build raises no toasts', () => {
    expect(isDesktopShell()).toBe(false)
  })

  it('is true once Tauri has injected its marker', () => {
    ;(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    try {
      expect(isDesktopShell()).toBe(true)
    } finally {
      delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
    }
  })
})
