/**
 * Launch-at-login adapter (issue #82).
 *
 * What's checked here is the same half `tray.test.ts` checks for the tray
 * adapter: that a browser build (no Tauri, no `autostart_*` commands) never
 * reaches for an API that isn't there.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { autostartStatus, isAutostartDesktopAvailable, setAutostartEnabled } from './autostart'

beforeEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
})

describe('in the browser build', () => {
  it('reports no desktop availability', () => {
    expect(isAutostartDesktopAvailable()).toBe(false)
  })

  it('reports launch-at-login as off rather than throwing', async () => {
    await expect(autostartStatus()).resolves.toBe(false)
  })

  it('refuses to change a setting that does not exist there', async () => {
    // Silently no-op-ing here would tell a caller a change took effect when
    // nothing happened — the opposite of what an opt-in toggle should do.
    await expect(setAutostartEnabled(true)).rejects.toThrow(/desktop app/)
  })
})
