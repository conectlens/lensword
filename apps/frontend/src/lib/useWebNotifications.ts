/**
 * Polls the notification outbox and raises browser notifications (issue #345).
 *
 * The web counterpart to `useDesktopNotifications`, with one deliberate
 * difference that is the whole point of the issue: that hook calls
 * `ensurePermission()` itself before its first poll, because in the desktop
 * shell the user already chose to install and launch an application. Here,
 * permission is never requested — this hook only ever *reads* whether it was
 * already granted from a click in Settings. A hook that prompted on mount
 * would be exactly the unsolicited behaviour the desktop module was written
 * to avoid, and a denial is permanent.
 *
 * Polling rather than a push transport, for the same reason the desktop hook
 * gives: the backend already durably records what is owed, so a missed poll
 * costs latency and nothing else, whereas a service worker with a push
 * subscription adds a reconnect story, a second auth path, and a server-side
 * subscription registry for a payload that says "you have words due".
 */

import { useEffect, useRef, useState } from 'react'
import { drainOnce, shouldDeliver } from './webNotifications'

// Matches the desktop hook. A reminder is a nudge; half a minute of latency on
// one is imperceptible, and the request is a single indexed query.
export const POLL_INTERVAL_MS = 30_000

/** Broadcast when the Settings toggle changes, so the hook starts or stops
 *  without waiting for a reload. `storage` events only fire in *other* tabs,
 *  so a same-tab signal is needed as well. */
export const WEB_NOTIFICATIONS_CHANGED_EVENT = 'lensword:web-notifications-changed'

/**
 * @param enabled false while signed out — the outbox endpoint is
 * authenticated, and polling it without a token would only produce 401s.
 */
export function useWebNotifications(enabled: boolean): void {
  // Re-read the opt-in when Settings changes it. Held in state rather than
  // read inline so the effect below actually re-runs on the change.
  const [deliverable, setDeliverable] = useState(() => shouldDeliver())

  useEffect(() => {
    function refresh() {
      setDeliverable(shouldDeliver())
    }
    window.addEventListener(WEB_NOTIFICATIONS_CHANGED_EVENT, refresh)
    // Another tab toggling the setting writes to localStorage; honour that too
    // rather than leaving tabs disagreeing until they are reloaded.
    window.addEventListener('storage', refresh)
    return () => {
      window.removeEventListener(WEB_NOTIFICATIONS_CHANGED_EVENT, refresh)
      window.removeEventListener('storage', refresh)
    }
  }, [])

  // Held in a ref so a slow cycle cannot overlap the next tick. Two concurrent
  // drains would both collect the same page, and the second would raise a
  // duplicate notification before the first acknowledged.
  const draining = useRef(false)

  useEffect(() => {
    if (!enabled || !deliverable) return

    let cancelled = false

    async function cycle() {
      if (draining.current || cancelled) return
      // Permission can be revoked from site settings mid-session, which no
      // event tells us about. Checking each cycle means the app stops trying
      // rather than throwing on every tick.
      if (!shouldDeliver()) return
      draining.current = true
      try {
        // Keep draining while pages come back full, so a backlog clears in one
        // cycle instead of one notification per interval.
        let shown = 0
        do {
          shown = await drainOnce()
        } while (shown > 0 && !cancelled)
      } catch {
        // A network blip or an expired token. The outbox is durable and
        // acknowledgement has not happened, so the next cycle picks it up.
      } finally {
        draining.current = false
      }
    }

    void cycle()
    const timer = setInterval(() => void cycle(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [enabled, deliverable])
}
