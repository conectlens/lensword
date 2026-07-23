/**
 * Resolves the API base URL at runtime.
 *
 * In the browser this is the build-time `VITE_API_URL`, exactly as before. In
 * the desktop shell it is whatever the Tauri host process resolved and
 * validated — the host checks that the endpoint is a loopback address or an
 * explicit HTTPS origin, so that rule cannot be skipped from here.
 *
 * This module is the one adapter boundary ADR 0001 permits inside
 * `frontend/src`: it is typed, and it works unchanged in the browser build.
 */

const BROWSER_FALLBACK: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/** Shape returned by the shell's `get_api_config` command. */
interface ApiConfig {
  base_url: string
  source: string
}

/**
 * True when running inside the Tauri shell.
 *
 * Feature-detected rather than compiled in, so one frontend build serves both
 * the browser deployment and the desktop shell.
 */
function isDesktopShell(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

let pending: Promise<string> | null = null

async function load(): Promise<string> {
  if (!isDesktopShell()) return BROWSER_FALLBACK

  // Imported dynamically so the browser build never pulls the Tauri client into
  // its main chunk.
  const { invoke } = await import('@tauri-apps/api/core')
  const config = await invoke<ApiConfig>('get_api_config')

  // The field name is a wire contract with the host process, pinned on that
  // side by `serializes_with_the_field_names_the_frontend_reads`. Checking it
  // here too means a rename fails loudly instead of memoizing `undefined` and
  // sending every later request to `undefined/api/v1/...`.
  if (typeof config?.base_url !== 'string' || config.base_url === '') {
    throw new Error('the desktop shell returned no API endpoint')
  }

  return config.base_url
}

/**
 * The API base URL, resolved once and reused.
 *
 * A rejected resolution is not cached, so a transient failure does not
 * permanently break the client for the life of the process.
 */
export function resolveApiBase(): Promise<string> {
  if (!pending) {
    pending = load().catch((err) => {
      pending = null
      throw err
    })
  }
  return pending
}

/** Test seam — clears the memoized resolution between cases. */
export function resetApiBaseForTests(): void {
  pending = null
}
