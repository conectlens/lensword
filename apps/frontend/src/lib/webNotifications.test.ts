/**
 * Browser notification support detection, permission and opt-in (issue #345).
 *
 * The load-bearing test in this file is the one asserting that merely
 * importing and using this module never calls `Notification.requestPermission`.
 * A denial is permanent for an origin, so an accidental prompt on page load
 * does not just annoy one user — it removes the feature for them forever, and
 * no later fix can win the permission back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  currentPermission,
  isEnabled,
  requestPermission,
  setEnabled,
  shouldDeliver,
  show,
  webNotificationSupport,
} from './webNotifications'

const STORAGE_KEY = 'lensword.web-notifications.enabled'

function stubNotification(permission: NotificationPermission) {
  const request = vi.fn(async () => permission)
  const constructed: Array<{ title: string; body?: string }> = []

  class FakeNotification {
    static permission = permission
    static requestPermission = request
    onclick: (() => void) | null = null
    close = vi.fn()
    constructor(title: string, options?: NotificationOptions) {
      constructed.push({ title, body: options?.body })
    }
  }

  vi.stubGlobal('Notification', FakeNotification)
  return { request, constructed }
}

beforeEach(() => {
  window.localStorage.clear()
  vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('support detection', () => {
  it('reports supported on a secure page with the API present', () => {
    stubNotification('default')
    expect(webNotificationSupport()).toBe('supported')
  })

  it('reports unsupported when the browser has no Notification API', () => {
    // Deliberately removing an API a browser may not have.
    delete (window as unknown as { Notification?: unknown }).Notification
    expect(webNotificationSupport()).toBe('unsupported')
  })

  it('reports an insecure context rather than pretending the browser is broken', () => {
    stubNotification('default')
    vi.stubGlobal('isSecureContext', false)
    expect(webNotificationSupport()).toBe('insecure-context')
  })

  it('stands down inside the desktop shell, which raises OS toasts itself', () => {
    stubNotification('granted')
    vi.stubGlobal('__TAURI_INTERNALS__', {})
    // Both paths drain the same outbox, so running both would show every
    // reminder twice.
    expect(webNotificationSupport()).toBe('desktop-shell')
  })
})

describe('permission', () => {
  it('is never requested as a side effect of reading it', () => {
    const { request } = stubNotification('default')

    currentPermission()
    isEnabled()
    shouldDeliver()
    webNotificationSupport()

    // The whole point of the issue: an origin gets one prompt, ever.
    expect(request).not.toHaveBeenCalled()
  })

  it('is requested when — and only when — explicitly asked for', async () => {
    const { request } = stubNotification('granted')

    await expect(requestPermission()).resolves.toBe('granted')

    expect(request).toHaveBeenCalledTimes(1)
  })

  it('reads live rather than from a cache, so a revoked permission is noticed', () => {
    stubNotification('granted')
    expect(currentPermission()).toBe('granted')

    // The user revokes it from site settings; nothing notifies the page.
    stubNotification('denied')
    expect(currentPermission()).toBe('denied')
  })

  it('answers denied without prompting where notifications cannot work at all', async () => {
    const { request } = stubNotification('default')
    vi.stubGlobal('isSecureContext', false)

    await expect(requestPermission()).resolves.toBe('denied')
    expect(request).not.toHaveBeenCalled()
  })

  it('survives a browser whose requestPermission rejects instead of resolving', async () => {
    // Older Safari implements only the callback form.
    class RejectingNotification {
      static permission: NotificationPermission = 'default'
      static requestPermission = vi.fn(async () => {
        throw new TypeError('not a function')
      })
    }
    vi.stubGlobal('Notification', RejectingNotification)

    await expect(requestPermission()).resolves.toBe('default')
  })
})

describe('the per-browser opt-in', () => {
  it('defaults to off — granting permission is not the same as asking for reminders', () => {
    stubNotification('granted')
    expect(isEnabled()).toBe(false)
    expect(shouldDeliver()).toBe(false)
  })

  it('persists across reloads', () => {
    stubNotification('granted')
    setEnabled(true)
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('true')
    expect(isEnabled()).toBe(true)
  })

  it('requires both the opt-in and a live permission before delivering', () => {
    stubNotification('granted')
    setEnabled(true)
    expect(shouldDeliver()).toBe(true)

    // Permission revoked in site settings after opting in.
    stubNotification('denied')
    expect(isEnabled()).toBe(true)
    expect(shouldDeliver()).toBe(false)
  })

  it('treats a browser that cannot store the opt-in as opted out', () => {
    stubNotification('granted')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('localStorage is unavailable')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('localStorage is unavailable')
    })

    // Safari's private mode has historically done exactly this. It must not
    // take the settings page down with it.
    expect(() => setEnabled(true)).not.toThrow()
    expect(isEnabled()).toBe(false)
  })
})

describe('showing a notification', () => {
  it('passes the backend-authored title and body through unchanged', async () => {
    const { constructed } = stubNotification('granted')
    setEnabled(true)

    await show('Time to review', '3 words are due')

    // The backend is where the lock-screen redaction decision is made, so a
    // client must not rebuild the body itself.
    expect(constructed).toEqual([{ title: 'Time to review', body: '3 words are due' }])
  })

  it('refuses rather than throwing something unrecognisable when not permitted', async () => {
    stubNotification('denied')
    await expect(show('Time to review', '3 words are due')).rejects.toThrow(/not permitted/i)
  })
})
