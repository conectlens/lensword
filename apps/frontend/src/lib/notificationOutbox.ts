/**
 * Draining the notification outbox, independent of who raises the toast.
 *
 * The backend records what a client is owed (issue #27) and a client collects
 * it. That collect → show → acknowledge loop is identical whether the toast is
 * an OS notification raised by the Tauri shell (issue #31) or a browser
 * notification raised by an open tab (issue #345) — only `show` differs. It
 * lives here so the web path does not have to import a module named for the
 * desktop one, and so a fix to the loop cannot land in one client and not the
 * other.
 *
 * The order is deliberate: acknowledging only *after* the toast is raised means
 * a client that dies mid-cycle re-shows a notification on next launch rather
 * than silently swallowing it — and the backend's ack is idempotent, so the
 * duplicate costs nothing.
 */

import { ApiRequestError, notificationsApi } from './api'
import type { NotificationActionId } from './types'

/**
 * Action buttons on a toast are the ideal, but support is uneven: they need a
 * registered action type on macOS, a channel on Android, and are unavailable
 * on some Linux notification daemons entirely. Rather than detect all that,
 * a plain click is treated as `start_session`, which is the action a click
 * most plausibly means and the only one that is safe to infer, since it
 * changes no server state on its own.
 */
export const DEFAULT_CLICK_ACTION: NotificationActionId = 'start_session'

/** How a client renders one notification. Title and body come from the
 *  backend, which is where the lock-screen redaction decision is made — a
 *  client must not reconstruct the body from `message` or it would undo that. */
export type ShowNotification = (title: string, body: string) => Promise<void>

/**
 * Carry out one action from a notification.
 *
 * Returns whether the review UI should be opened. A notification that expired
 * while it sat in the tray answers 409; that is an ordinary outcome — the user
 * clicked a stale toast — so it is swallowed rather than surfaced as an error.
 */
export async function act(
  notificationId: number,
  action: NotificationActionId,
): Promise<boolean> {
  try {
    const result = await notificationsApi.act(notificationId, action)
    return result.open_review
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 409) return false
    throw error
  }
}

/**
 * Collect what the client is owed, show it, and acknowledge it.
 *
 * Returns the number of notifications shown, which is what the caller needs to
 * decide whether to poll again immediately: the backend caps a page, so a full
 * one means there is more waiting.
 */
export async function drainOnce(showFn: ShowNotification): Promise<number> {
  const pending = await notificationsApi.listPending()
  if (pending.notifications.length === 0) return 0

  const shown: number[] = []
  for (const notification of pending.notifications) {
    try {
      await showFn(notification.title, notification.body)
      shown.push(notification.id)
    } catch {
      // Stop at the first failure rather than marking the rest delivered. The
      // unacknowledged ones stay pending and are retried next cycle.
      break
    }
  }

  if (shown.length > 0) await notificationsApi.acknowledge(shown)
  return shown.length
}
