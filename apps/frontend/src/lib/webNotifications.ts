/**
 * Browser notifications for the web app (issue #345).
 *
 * Deliberately not a port of `desktopNotifications.ts`. That module's own
 * docstring frames unsolicited browser notifications as the behaviour the
 * desktop shell exists to replace — and the distinction it draws is about
 * *consent*, not about the platform. A page that calls
 * `Notification.requestPermission()` on load, before the reader has decided
 * they want anything from it, is the pattern browsers grew a permanent-denial
 * state to punish: once denied, there is no second prompt, ever, and the
 * feature is gone for that origin.
 *
 * So the rule this module exists to enforce is that permission is requested
 * only from an explicit user action. Nothing here requests it on import, on
 * mount, or as a side effect of polling; `requestPermission` is exported for a
 * click handler to call and is never invoked from anywhere else in the app.
 *
 * The opt-in itself is stored locally rather than on the account, and that is
 * not a shortcut. Notification permission is granted per browser profile, so
 * an account-level flag would claim notifications were on in Safari because
 * the user granted them in Chrome, and the app would poll and show nothing.
 * The server-side channel settings (`desktop_enabled`, quiet hours, and the
 * rest of `recall_delivery.py`'s policy) still decide whether a notification
 * is owed at all — this only decides whether *this browser* raises it.
 */

import { isDesktopShell } from './desktopNotifications'
import { drainOnce as drainOutbox } from './notificationOutbox'

/** Why this browser can or cannot show notifications. */
export type WebNotificationSupport =
  /** The API exists and may be used. */
  | 'supported'
  /** No Notification API at all — an old browser, or iOS Safari outside an installed PWA. */
  | 'unsupported'
  /** The API exists but the page is not a secure context, where browsers refuse it. */
  | 'insecure-context'
  /** Running inside the Tauri shell, which raises OS notifications itself. */
  | 'desktop-shell'

const STORAGE_KEY = 'lensword.web-notifications.enabled'

export function webNotificationSupport(): WebNotificationSupport {
  if (typeof window === 'undefined') return 'unsupported'
  // Checked first: the shell serves this same build, and both paths draining
  // the same outbox would show every reminder twice.
  if (isDesktopShell()) return 'desktop-shell'
  if (!('Notification' in window)) return 'unsupported'
  // Browsers require a secure context. `isSecureContext` is true for https and
  // for localhost, so a developer running the app locally is not told their
  // browser is broken.
  if (window.isSecureContext === false) return 'insecure-context'
  return 'supported'
}

/**
 * This browser's current permission, or null where there is no API to ask.
 *
 * Read live from the browser rather than cached: the user can revoke
 * permission from site settings at any time, and a cached "granted" would
 * leave the app polling for toasts it can no longer raise.
 */
export function currentPermission(): NotificationPermission | null {
  if (webNotificationSupport() !== 'supported') return null
  return Notification.permission
}

/**
 * Ask this browser for permission. **Call only from a user gesture.**
 *
 * There is exactly one chance: a denial is permanent for the origin and no
 * later call will re-prompt. That is why nothing in this app calls this
 * outside a click handler.
 */
export async function requestPermission(): Promise<NotificationPermission> {
  if (webNotificationSupport() !== 'supported') return 'denied'
  try {
    return await Notification.requestPermission()
  } catch {
    // Older Safari implements only the callback form and rejects the promise.
    return Notification.permission
  }
}

/** Raise one notification. Clicking it focuses the tab that owns it. */
export async function show(title: string, body: string): Promise<void> {
  if (currentPermission() !== 'granted') throw new Error('Notifications are not permitted.')
  const notification = new Notification(title, { body })
  notification.onclick = () => {
    // Focus rather than navigate: this module has no router access, and
    // guessing a destination would be worse than landing the user where they
    // left off. Recording the click as a `start_session` action the way the
    // desktop shell does is a separate, larger change.
    window.focus()
    notification.close()
  }
}

/**
 * Whether *this browser* is opted in.
 *
 * Storage can throw — Safari's private mode has historically made
 * `localStorage` unavailable — and a browser that cannot remember the opt-in
 * is treated as opted out rather than allowed to crash the settings page.
 */
export function isEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function setEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(enabled))
  } catch {
    // Nothing useful to do: the toggle simply will not persist across reloads.
  }
}

/**
 * True when this browser should actually be polling for notifications.
 *
 * Both halves are required and they are genuinely different facts: the user
 * asked for notifications here, *and* the browser will let us raise one. A
 * user who opted in and later revoked permission in site settings must stop
 * being polled for.
 */
export function shouldDeliver(): boolean {
  return isEnabled() && currentPermission() === 'granted'
}

/** Collect what this browser is owed, show it, and acknowledge it. */
export async function drainOnce(showFn: typeof show = show): Promise<number> {
  return drainOutbox(showFn)
}
