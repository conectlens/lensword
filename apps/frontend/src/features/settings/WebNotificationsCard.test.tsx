/**
 * The Settings opt-in (issue #345).
 *
 * Every browser state gets its own assertion because each one is a dead end a
 * user cannot diagnose from a greyed-out switch: blocked can only be undone in
 * browser settings, an insecure page can never work, and an unsupported
 * browser never will. "Communicated clearly instead of failing silently" is
 * the acceptance criterion, so the copy is what is tested.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WebNotificationsCard } from './WebNotificationsCard'

const STORAGE_KEY = 'lensword.web-notifications.enabled'

const requestPermission = vi.fn<() => Promise<NotificationPermission>>()

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

beforeEach(() => {
  window.localStorage.clear()
  requestPermission.mockReset()
  requestPermission.mockResolvedValue('granted')
  vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

it('does not ask for permission just by being rendered', async () => {
  stubNotification('default')

  render(<WebNotificationsCard />)
  await screen.findByRole('button', { name: /turn on notifications/i })

  // The prompt belongs to the click below, never to mount. A browser gives an
  // origin one answer, and asking before explaining spends it.
  expect(requestPermission).not.toHaveBeenCalled()
})

it('asks for permission on an explicit click, and opts this browser in once granted', async () => {
  stubNotification('default')
  render(<WebNotificationsCard />)
  fireEvent.click(await screen.findByRole('button', { name: /turn on notifications/i }))

  expect(requestPermission).toHaveBeenCalledTimes(1)
  await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBe('true'))
})

it('does not opt in when the user dismisses or blocks the browser prompt', async () => {
  stubNotification('default')
  requestPermission.mockResolvedValue('denied')
  render(<WebNotificationsCard />)
  fireEvent.click(await screen.findByRole('button', { name: /turn on notifications/i }))

  await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).not.toBe('true'))
})

it('explains that a blocked permission can only be undone in browser settings', async () => {
  stubNotification('denied')

  render(<WebNotificationsCard />)

  const message = await screen.findByRole('alert')
  expect(message).toHaveTextContent(/blocked/i)
  expect(message).toHaveTextContent(/site settings/i)
  // Offering a button that cannot possibly work would be worse than saying so.
  expect(screen.queryByRole('button', { name: /turn on notifications/i })).toBeNull()
})

it('says so when the browser has no notification support at all', async () => {
  // Deliberately removing an API a browser may not have.
  delete (window as unknown as { Notification?: unknown }).Notification

  render(<WebNotificationsCard />)

  expect(await screen.findByText(/does not support notifications/i)).toBeInTheDocument()
  // Reminders are not lost — they are still waiting in the app.
  expect(screen.getByText(/waiting for you/i)).toBeInTheDocument()
})

it('says so on an insecure page rather than looking broken', async () => {
  stubNotification('default')
  vi.stubGlobal('isSecureContext', false)

  render(<WebNotificationsCard />)

  expect(await screen.findByText(/secure \(HTTPS\) pages/i)).toBeInTheDocument()
})

it('renders nothing inside the desktop shell, which raises OS toasts itself', () => {
  stubNotification('granted')
  vi.stubGlobal('__TAURI_INTERNALS__', {})

  const { container } = render(<WebNotificationsCard />)

  // A second switch here would only let a user turn on duplicates.
  expect(container).toBeEmptyDOMElement()
})

it('lets an already-permitted browser turn delivery off again without losing permission', async () => {
  stubNotification('granted')
  window.localStorage.setItem(STORAGE_KEY, 'true')
  render(<WebNotificationsCard />)
  fireEvent.click(await screen.findByRole('checkbox'))

  await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBe('false'))
  expect(requestPermission).not.toHaveBeenCalled()
})
