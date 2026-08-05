/**
 * OS-native notifications in the desktop shell (ROADMAP 3.2, issue #31).
 *
 * The backend cannot raise a toast: ADR 0002 made the desktop app remote-only,
 * so the process that decides a notification is owed and the process that owns
 * the notification tray are different ones, usually on different machines. The
 * backend records what is owed (issue #27) and this drains it.
 *
 * The loop is deliberately: collect → show → acknowledge. Acknowledging only
 * after the toast is raised means a shell that dies mid-cycle re-shows a
 * notification on next launch rather than silently swallowing it — and the
 * backend's ack is idempotent, so the duplicate costs nothing.
 *
 * This is the third typed adapter boundary ADR 0001 permits inside
 * `apps/frontend/src`, alongside `runtimeConfig.ts` and `credentialStore.ts`: it is
 * feature-detected, so one build serves both the browser deployment and the
 * shell. In the browser every function here is a no-op — a web page raising
 * unsolicited desktop notifications is the behaviour the shell exists to
 * replace, not something to reproduce.
 */

import { ApiRequestError, notificationsApi } from './api'
import type { DesktopNotification, NotificationActionId } from './types'

/**
 * Action buttons on a toast are the ideal, but support is uneven: they need a
 * registered action type on macOS, a channel on Android, and are unavailable
 * on some Linux notification daemons entirely. Rather than detect all that,
 * the shell registers buttons where the plugin accepts them and treats a
 * plain click as `start_session` everywhere else — which is the action a
 * click most plausibly means, and the only one that is safe to infer, since
 * it changes no server state on its own.
 */
export const DEFAULT_CLICK_ACTION: NotificationActionId = 'start_session'

/**
 * True when running inside the Tauri shell. Feature-detected on the marker
 * Tauri injects into the webview, matching `runtimeConfig.ts` and
 * `credentialStore.ts` rather than compiling in a build flag.
 */
export function isDesktopShell(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

/**
 * Ask for notification permission once, returning whether it was granted.
 *
 * macOS and Windows both refuse to display anything until the user has agreed,
 * and on macOS the prompt only appears for a signed, installed application —
 * so a denial here is a normal outcome to handle, not an error to report.
 */
export async function ensurePermission(): Promise<boolean> {
  if (!isDesktopShell()) return false
  try {
    const { isPermissionGranted, requestPermission } = await import('@tauri-apps/plugin-notification')
    if (await isPermissionGranted()) return true
    return (await requestPermission()) === 'granted'
  } catch {
    // A shell built without the plugin, or a platform that has no notification
    // service. Reminders still accumulate server-side and are visible in-app.
    return false
  }
}

export async function show(title: string, body: string): Promise<void> {
  const { sendNotification } = await import('@tauri-apps/plugin-notification')
  sendNotification({ title, body })
}

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
 * Collect what the tray is owed, show it, and acknowledge it.
 *
 * Returns the number of notifications shown, which is what the caller needs to
 * decide whether to poll again immediately: the backend caps a page, so a full
 * one means there is more waiting.
 */
export async function drainOnce(showFn: typeof show = show): Promise<number> {
  const pending = await notificationsApi.listPending()
  if (pending.notifications.length === 0) return 0

  const shown: number[] = []
  for (const notification of pending.notifications) {
    try {
      // title/body come from the backend, which is where the lock-screen
      // redaction decision is made — the shell must not reconstruct the body
      // from `message` or it would undo that.
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
