/**
 * Polls the notification outbox and raises OS toasts (ROADMAP 3.2, issue #31).
 *
 * Polling rather than a push transport, deliberately. The backend already
 * durably records what the tray is owed (issue #27), so a missed poll costs
 * latency and nothing else — whereas a socket adds a reconnect story, a
 * heartbeat and a second auth path for a feature whose whole payload is "you
 * have words due". A push transport becomes worth it at #87's failover model,
 * not before.
 */

import { useEffect, useRef } from 'react'
import { drainOnce, ensurePermission, isDesktopShell } from './desktopNotifications'

// A reminder is a nudge. Half a minute of latency on one is imperceptible, and
// the request is a single indexed query against rows this account owns.
export const POLL_INTERVAL_MS = 30_000

/**
 * @param enabled false while signed out — the endpoint is authenticated, and
 * polling it without a token would only produce a stream of 401s.
 */
export function useDesktopNotifications(enabled: boolean): void {
  // Held in a ref so a slow cycle cannot overlap the next tick. Two concurrent
  // drains would both collect the same page, and the second would raise a
  // duplicate toast before the first acknowledged.
  const draining = useRef(false)

  useEffect(() => {
    if (!enabled || !isDesktopShell()) return

    let cancelled = false
    let timer: ReturnType<typeof setInterval> | undefined

    async function cycle() {
      if (draining.current || cancelled) return
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

    void (async () => {
      // Permission is requested once per session, before the first poll: a
      // denial means no toast can be raised, so polling would be busywork.
      if (!(await ensurePermission()) || cancelled) return
      void cycle()
      timer = setInterval(() => void cycle(), POLL_INTERVAL_MS)
    })()

    return () => {
      cancelled = true
      if (timer !== undefined) clearInterval(timer)
    }
  }, [enabled])
}
