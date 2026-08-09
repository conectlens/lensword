/**
 * The web polling hook (issue #345).
 *
 * Two properties matter here and neither is about rendering. The hook must
 * never ask for permission — that belongs to a click in Settings, and a
 * denial is permanent — and it must not poll an authenticated endpoint when
 * it could not raise a notification anyway.
 */
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const listPending = vi.fn()
const acknowledge = vi.fn()

class FakeApiRequestError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

vi.mock('./api', () => ({
  ApiRequestError: FakeApiRequestError,
  notificationsApi: {
    listPending: () => listPending(),
    acknowledge: (ids: number[]) => acknowledge(ids),
    act: vi.fn(),
  },
}))

const { useWebNotifications, WEB_NOTIFICATIONS_CHANGED_EVENT } = await import('./useWebNotifications')

const STORAGE_KEY = 'lensword.web-notifications.enabled'

const requestPermission = vi.fn(async () => 'granted' as NotificationPermission)

function stubNotification(permission: NotificationPermission) {
  class FakeNotification {
    static permission = permission
    static requestPermission = requestPermission
    onclick: (() => void) | null = null
    close = vi.fn()
    constructor(_title: string, _options?: NotificationOptions) {}
  }
  vi.stubGlobal('Notification', FakeNotification)
}

function Harness({ enabled }: { enabled: boolean }) {
  useWebNotifications(enabled)
  return null
}

function empty() {
  return { notifications: [] }
}

function pending(...bodies: string[]) {
  return {
    notifications: bodies.map((body, index) => ({
      id: index + 1,
      message: body,
      created_at: '2026-08-09T09:00:00',
      title: 'LensWord',
      body,
    })),
  }
}

beforeEach(() => {
  listPending.mockReset()
  acknowledge.mockReset()
  requestPermission.mockClear()
  window.localStorage.clear()
  vi.stubGlobal('isSecureContext', true)
  stubNotification('granted')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('permission', () => {
  it('is never requested by mounting the hook', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'true')
    listPending.mockResolvedValue(empty())

    render(<Harness enabled />)
    await waitFor(() => expect(listPending).toHaveBeenCalled())

    // The desktop hook does call ensurePermission() on mount. This one must
    // not: an origin gets one prompt, and spending it without the user having
    // asked removes the feature permanently.
    expect(requestPermission).not.toHaveBeenCalled()
  })
})

describe('when it polls', () => {
  it('does not poll while signed out', () => {
    window.localStorage.setItem(STORAGE_KEY, 'true')
    render(<Harness enabled={false} />)
    // The outbox endpoint is authenticated; polling it would produce only 401s.
    expect(listPending).not.toHaveBeenCalled()
  })

  it('does not poll when permission was granted but the user has not opted in', () => {
    render(<Harness enabled />)
    expect(listPending).not.toHaveBeenCalled()
  })

  it('does not poll when the user opted in but permission was later revoked', () => {
    window.localStorage.setItem(STORAGE_KEY, 'true')
    stubNotification('denied')
    render(<Harness enabled />)
    expect(listPending).not.toHaveBeenCalled()
  })

  it('starts polling when Settings turns it on, without needing a reload', async () => {
    listPending.mockResolvedValue(empty())
    render(<Harness enabled />)
    expect(listPending).not.toHaveBeenCalled()

    window.localStorage.setItem(STORAGE_KEY, 'true')
    window.dispatchEvent(new Event(WEB_NOTIFICATIONS_CHANGED_EVENT))

    await waitFor(() => expect(listPending).toHaveBeenCalled())
  })
})

describe('draining', () => {
  it('shows what is owed and acknowledges only what was shown', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'true')
    listPending.mockResolvedValueOnce(pending('3 words are due')).mockResolvedValue(empty())

    render(<Harness enabled />)

    await waitFor(() => expect(acknowledge).toHaveBeenCalledWith([1]))
  })

  it('keeps draining while pages come back full, so a backlog clears in one cycle', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'true')
    listPending
      .mockResolvedValueOnce(pending('first'))
      .mockResolvedValueOnce(pending('second'))
      .mockResolvedValue(empty())

    render(<Harness enabled />)

    await waitFor(() => expect(acknowledge).toHaveBeenCalledTimes(2))
  })

  it('swallows a failed cycle, leaving the outbox to be retried', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'true')
    listPending.mockRejectedValue(new Error('network blip'))

    render(<Harness enabled />)

    // Nothing acknowledged: the notifications are durable server-side and the
    // next cycle picks them up.
    await waitFor(() => expect(listPending).toHaveBeenCalled())
    expect(acknowledge).not.toHaveBeenCalled()
  })
})
