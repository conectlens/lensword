/**
 * Where the authentication token lives.
 *
 * Browser build: `localStorage`, exactly as before, under `lensword_token`.
 *
 * Desktop shell: the operating-system credential store, reached through typed
 * Tauri commands (`credential_get` / `credential_set` / `credential_clear`).
 * ADR 0001's security requirements forbid persisting the token in webview
 * `localStorage` in the shell; there it must sit behind a native adapter backed
 * by OS credential storage, exposing only get, set and clear.
 *
 * The frontend reads the token synchronously — every request builds an
 * `Authorization` header from it — but the native store is asynchronous. So the
 * token is hydrated once at startup into an in-memory cache; reads come from the
 * cache, writes update it immediately and persist in the background. This is the
 * second typed adapter boundary ADR 0001 permits inside `frontend/src`,
 * alongside `runtimeConfig.ts`: it is feature-detected, so one build serves both
 * the browser deployment and the desktop shell.
 */

const TOKEN_KEY = 'lensword_token'

/**
 * True when running inside the Tauri shell. Feature-detected on the marker Tauri
 * injects into the webview, matching `runtimeConfig.ts` rather than compiling in
 * a build flag.
 */
function isDesktopShell(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

// --- native backend (desktop shell only) ---------------------------------
//
// Imported dynamically so the browser build never pulls the Tauri client into
// its main chunk.

async function nativeLoad(): Promise<string | null> {
  const { invoke } = await import('@tauri-apps/api/core')
  return (await invoke<string | null>('credential_get')) ?? null
}

async function nativeSave(token: string): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('credential_set', { token })
}

async function nativeClear(): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('credential_clear')
}

// Native persistence is serialized through this promise chain so writes apply
// in the order they were requested — a `login` immediately followed by a
// `logout` must leave the store cleared, never re-set by a set that resolved
// after the clear. A rejected step is logged, not thrown: callers are
// synchronous, so an unhandled rejection here has nowhere to go.
let persistence: Promise<void> = Promise.resolve()

function enqueuePersist(op: () => Promise<void>): void {
  persistence = persistence.then(op).catch((err) => {
    console.error('failed to persist the auth token to the OS credential store', err)
  })
}

// --- in-memory cache ------------------------------------------------------

let cache: string | null = null
let hydrated = false

/**
 * Load the token into the in-memory cache once, at startup.
 *
 * Call this before the first authenticated request. In the shell it reads the
 * OS credential store; in the browser it reads `localStorage`. Idempotent.
 */
export async function hydrateToken(): Promise<void> {
  if (hydrated) return
  cache = isDesktopShell() ? await nativeLoad() : localStorage.getItem(TOKEN_KEY)
  hydrated = true
}

/**
 * The current token, read synchronously.
 *
 * In the browser, before hydrate has run, this falls through to `localStorage`
 * so a freshly loaded tab reads a token persisted by a previous session exactly
 * as it did before this adapter existed. In the shell the cache is the only
 * source — the token is never in `localStorage` there to fall through to.
 */
export function getToken(): string | null {
  if (!hydrated && !isDesktopShell()) return localStorage.getItem(TOKEN_KEY)
  return cache
}

/**
 * Set or clear the token.
 *
 * The cache is updated synchronously so a following `getToken()` is correct
 * immediately. Persistence to the backing store happens in the background; a
 * failed native write is surfaced to the console rather than thrown, because
 * callers (`login`, `logout`) are synchronous and a rejected promise here would
 * be unhandled. In the shell, `localStorage` is deliberately never written.
 */
export function setToken(token: string | null): void {
  cache = token
  hydrated = true

  if (isDesktopShell()) {
    enqueuePersist(() => (token !== null ? nativeSave(token) : nativeClear()))
    return
  }

  if (token !== null) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/**
 * Resolves once every persist queued so far has been dispatched. Test seam: the
 * native store is written asynchronously, so a test asserting on the `invoke`
 * calls awaits this first.
 */
export function credentialPersistenceSettled(): Promise<void> {
  return persistence
}

/** Test seam — clears the in-memory cache between cases. */
export function resetCredentialStoreForTests(): void {
  cache = null
  hydrated = false
  persistence = Promise.resolve()
}
