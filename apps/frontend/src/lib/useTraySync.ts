/**
 * Keeps the tray's due-count/pause/provider tooltip current, and turns tray
 * clicks into real navigation and a real pause toggle (issue #82).
 *
 * `tray.ts` already has the typed adapter for both directions; nothing here
 * calls a Tauri API directly. This hook is the piece that was still missing:
 * something that actually calls `setTrayStatus`/`onTrayAction` with live data
 * from the running app, the same gap `useDesktopNotifications` closed for the
 * notification outbox.
 */

import { useEffect, useRef } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { aiSettingsApi, groupsApi, settingsApi } from './api'
import { isDesktopShell } from './desktopNotifications'
import { onTrayAction, setTrayStatus } from './tray'

// Due counts and the pause flag change slowly enough that half a minute of
// staleness in a tray tooltip is imperceptible — the same interval and the
// same reasoning as useDesktopNotifications' poll.
export const TRAY_SYNC_INTERVAL_MS = 30_000

interface UseTraySyncOptions {
  /** false while signed out — every request below is authenticated. */
  enabled: boolean
  /**
   * `/api/v1/ai-settings` is admin-only (it configures the deployment's
   * effective AI provider, not a per-user preference), so a non-admin
   * session has no endpoint to read it from and the tray line is omitted
   * rather than guessed.
   */
  isAdmin: boolean
  navigate: NavigateFunction
}

export function useTraySync({ enabled, isAdmin, navigate }: UseTraySyncOptions): void {
  // Mirrors useDesktopNotifications: a slow cycle must not overlap the next
  // tick, or two in-flight syncs could race the tray tooltip backwards.
  const syncing = useRef(false)

  useEffect(() => {
    if (!enabled || !isDesktopShell()) return

    let cancelled = false
    let timer: ReturnType<typeof setInterval> | undefined

    async function sync() {
      if (syncing.current || cancelled) return
      syncing.current = true
      try {
        const [groups, recall] = await Promise.all([groupsApi.list(), settingsApi.getRecallSettings()])

        let aiProvider: string | null = null
        if (isAdmin) {
          try {
            const ai = await aiSettingsApi.get()
            aiProvider = ai.provider === 'ollama' ? `Ollama (${ai.model})` : null
          } catch {
            // Effective settings unreadable (e.g. mid-deploy); omit the line
            // rather than showing a stale or fabricated provider name.
            aiProvider = null
          }
        }
        if (cancelled) return

        await setTrayStatus({
          dueCount: groups.reduce((sum, g) => sum + g.due_count, 0),
          notificationsPaused: recall.notifications_paused,
          aiProvider,
          // Never polled here: confirming reachability means an HTTP round
          // trip to the Ollama host, which a tray tooltip refresh has no
          // business triggering every 30s. `null` is the type's own honest
          // "not yet checked" state, not a placeholder.
          localModelReady: null,
        })
      } catch {
        // A network blip or an expired token; the next cycle retries.
      } finally {
        syncing.current = false
      }
    }

    async function togglePause() {
      const current = await settingsApi.getRecallSettings()
      await settingsApi.updateRecallSettings({ ...current, notifications_paused: !current.notifications_paused })
      void sync()
    }

    void sync()
    timer = setInterval(() => void sync(), TRAY_SYNC_INTERVAL_MS)

    const unsubscribe = onTrayAction({ navigate, togglePause })

    return () => {
      cancelled = true
      if (timer !== undefined) clearInterval(timer)
      void unsubscribe.then((off) => off())
    }
  }, [enabled, isAdmin, navigate])
}
