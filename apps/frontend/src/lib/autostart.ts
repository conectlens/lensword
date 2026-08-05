/**
 * Launch-at-login, on the frontend side (issue #82).
 *
 * The fifth feature-detected adapter alongside `runtimeConfig`, `credentialStore`,
 * `desktopNotifications` and `clipboardCapture`. Every function is a no-op in
 * the browser build, where there is no OS launch mechanism to talk to.
 */

function desktop(): boolean { return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window }
async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> { const { invoke } = await import('@tauri-apps/api/core'); return invoke<T>(command, args) }

export function isAutostartDesktopAvailable(): boolean { return desktop() }

export async function autostartStatus(): Promise<boolean> {
  return desktop() ? invoke<boolean>('autostart_status') : false
}

export async function setAutostartEnabled(enabled: boolean): Promise<void> {
  if (!desktop()) throw new Error('Launch at login is available only in the desktop app.')
  await invoke('autostart_set_enabled', { enabled })
}
