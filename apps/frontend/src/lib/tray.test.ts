/**
 * Tray action routing and status reporting (issue #82).
 *
 * The Rust side has its own tests for id round-tripping and close behaviour.
 * What is checked here is the half Rust deliberately does not own: where each
 * action leads, and that a desktop with no system tray degrades quietly rather
 * than erroring.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { routeFor, setTrayStatus, type TrayAction, type TrayStatus } from './tray'

const status: TrayStatus = {
  dueCount: 3,
  notificationsPaused: false,
  aiProvider: 'Ollama',
  localModelReady: true,
}

beforeEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
})

describe('routeFor', () => {
  it('sends the navigating actions to their pages', () => {
    expect(routeFor('add_word')).toBe('/words/new')
    expect(routeFor('show_window')).toBe('/dashboard')
  })

  it('asks for a short session rather than the full queue', () => {
    // The menu item says "five-minute review". A route without the limit would
    // open the whole backlog, which is a different promise.
    expect(routeFor('quick_review')).toContain('limit=5')
  })

  it('gives no route for actions that are not destinations', () => {
    // One changes a setting, the other ends the process. Navigating for either
    // would be wrong rather than merely useless.
    expect(routeFor('toggle_pause')).toBeNull()
    expect(routeFor('quit')).toBeNull()
  })

  it('has an answer for every action the shell can emit', () => {
    // A new variant in Rust that nothing here handled would produce a menu
    // item that silently does nothing.
    const all: TrayAction[] = ['add_word', 'quick_review', 'toggle_pause', 'show_window', 'quit']
    for (const action of all) {
      expect(() => routeFor(action)).not.toThrow()
    }
  })
})

describe('setTrayStatus', () => {
  it('does nothing in the browser build', async () => {
    // There is no tray in a browser tab, and reaching for the Tauri API there
    // would throw on a perfectly normal deployment.
    await expect(setTrayStatus(status)).resolves.toBeUndefined()
  })

  it('swallows a desktop with no system tray', async () => {
    // Common on Linux. The application is fully usable without one, so this
    // must not surface as an error.
    ;(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    vi.doMock('@tauri-apps/api/core', () => ({
      invoke: () => Promise.reject(new Error('no tray available')),
    }))

    await expect(setTrayStatus(status)).resolves.toBeUndefined()
  })
})
