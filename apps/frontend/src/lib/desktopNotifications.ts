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

import { act, DEFAULT_CLICK_ACTION, drainOnce as drainOutbox } from './notificationOutbox'

// The collect → show → acknowledge loop and the click-action constant moved to
// `notificationOutbox.ts` when the web client (issue #345) grew the same need:
// only `show` and `ensurePermission` were ever desktop-specific. Re-exported
// here so existing importers of this module are unaffected.
export { act, DEFAULT_CLICK_ACTION }

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

/** Collect what the tray is owed, show it as an OS toast, acknowledge it. */
export async function drainOnce(showFn: typeof show = show): Promise<number> {
  return drainOutbox(showFn)
}
