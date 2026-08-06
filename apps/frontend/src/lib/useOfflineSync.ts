/**
 * Replays the offline mutation queue on reconnect (issue #218).
 *
 * Two triggers: the browser's own `online` event, and once on mount — the
 * event only fires on a transition, so an app opened while already back
 * online (the common case: someone edited vocabulary offline, closed the
 * laptop, and reopened it later on wifi) would otherwise leave a queue
 * sitting unsent until the next transition that never comes.
 */
import { useEffect, useRef } from 'react'
import { queueLength, replayQueue } from './offlineQueue'

export function useOfflineSync(enabled: boolean): void {
  // Held in a ref so a slow replay cannot overlap the next trigger — the
  // same reason useDesktopNotifications guards its own cycle.
  const replaying = useRef(false)

  useEffect(() => {
    if (!enabled) return

    let cancelled = false

    async function attempt() {
      if (replaying.current || cancelled || queueLength() === 0) return
      replaying.current = true
      try {
        await replayQueue()
      } catch {
        // Still offline, or the server is unreachable — the queue is
        // untouched, and the next trigger (another `online` event, or the
        // next reconnect) tries again.
      } finally {
        replaying.current = false
      }
    }

    void attempt()
    window.addEventListener('online', attempt)
    return () => {
      cancelled = true
      window.removeEventListener('online', attempt)
    }
  }, [enabled])
}
