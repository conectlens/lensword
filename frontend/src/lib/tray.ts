/**
 * Tray / menu-bar actions, on the frontend side (issue #82).
 *
 * The shell emits `tray://action` and this decides what it means. Two rules
 * meet here and both point the same way: UI code must not call Tauri APIs
 * directly, and the shell must not own the router. So the Rust side names the
 * action and this maps it to a route — one routing table, in the language that
 * has the router.
 *
 * The fourth feature-detected adapter alongside `runtimeConfig`,
 * `credentialStore` and `desktopNotifications`. Every function is a no-op in
 * the browser build, where there is no tray to talk to.
 */

import { isDesktopShell } from './desktopNotifications'

/** Mirrors `TrayAction` in `desktop/src-tauri/src/tray.rs`. */
export type TrayAction =
  | 'add_word'
  | 'quick_review'
  | 'toggle_pause'
  | 'show_window'
  | 'quit'

export interface TrayStatus {
  dueCount: number
  notificationsPaused: boolean
  /** Display name of the current AI provider, or null when disabled. */
  aiProvider: string | null
  /**
   * Whether a local model is reachable. `null` means not yet checked —
   * distinct from `false`, so the menu can say "checking" rather than
   * asserting an outage nothing has observed.
   */
  localModelReady: boolean | null
}

/**
 * Where each action leads.
 *
 * `toggle_pause` and `quit` are absent deliberately: one changes a setting and
 * the other ends the process, and neither is a destination. A missing entry
 * means "handle this without navigating", not "unknown action".
 */
const ROUTES: Partial<Record<TrayAction, string>> = {
  add_word: '/words/new',
  quick_review: '/review?mode=standard&limit=5',
  show_window: '/dashboard',
}

export function routeFor(action: TrayAction): string | null {
  return ROUTES[action] ?? null
}

/** Push counts into the tray so its tooltip reflects reality. */
export async function setTrayStatus(status: TrayStatus): Promise<void> {
  if (!isDesktopShell()) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('tray_set_status', { status })
  } catch {
    // A shell built without the tray, or a Linux desktop with no system tray
    // at all — which is common enough that it must not surface as an error.
    // The app is fully usable without one.
  }
}

/**
 * Subscribe to tray actions. Returns an unsubscribe function.
 *
 * `navigate` and `togglePause` are injected rather than imported so this stays
 * testable without a router or an API client, and so the caller decides what
 * pausing means rather than this reaching into settings.
 */
export async function onTrayAction(
  handlers: {
    navigate: (route: string) => void
    togglePause: () => void | Promise<void>
  },
): Promise<() => void> {
  if (!isDesktopShell()) return () => {}
  try {
    const { listen } = await import('@tauri-apps/api/event')
    return await listen<TrayAction>('tray://action', (event) => {
      const action = event.payload
      if (action === 'toggle_pause') {
        void handlers.togglePause()
        return
      }
      const route = routeFor(action)
      if (route) handlers.navigate(route)
    })
  } catch {
    return () => {}
  }
}
