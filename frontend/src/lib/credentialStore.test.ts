import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  clearToken,
  credentialPersistenceSettled,
  getToken,
  hydrateToken,
  resetCredentialStoreForTests,
  setToken,
} from './credentialStore'

const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

/** The webview object Tauri injects its marker into. */
const webview = window as unknown as Record<string, unknown>
const TOKEN_KEY = 'lensword_token'

function enterDesktopShell(): void {
  webview.__TAURI_INTERNALS__ = {}
}

afterEach(async () => {
  // Fire-and-forget persists from a test must finish before the mock is reset,
  // or a late `invoke` resolves into the next test's call log.
  await credentialPersistenceSettled()
  delete webview.__TAURI_INTERNALS__
  invoke.mockReset()
  localStorage.clear()
  resetCredentialStoreForTests()
})

describe('credentialStore — browser build', () => {
  it('reads and writes the token through localStorage, unchanged from before', () => {
    setToken('abc.def.ghi')
    expect(getToken()).toBe('abc.def.ghi')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('abc.def.ghi')
  })

  it('clears the token from localStorage when set to null', () => {
    setToken('abc.def.ghi')
    setToken(null)
    expect(getToken()).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })

  it('reads a token persisted by a previous session before hydrate runs', () => {
    localStorage.setItem(TOKEN_KEY, 'persisted.token')
    // A fresh page load reads the persisted token synchronously, as before,
    // without waiting for hydrate.
    expect(getToken()).toBe('persisted.token')
  })

  it('never calls the shell in the browser build', async () => {
    await hydrateToken()
    setToken('abc')
    setToken(null)
    expect(invoke).not.toHaveBeenCalled()
  })
})

describe('credentialStore — desktop shell', () => {
  it('hydrates the token from the OS credential store, not localStorage', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue('token.from.keychain')

    await hydrateToken()

    expect(invoke).toHaveBeenCalledWith('credential_get')
    expect(getToken()).toBe('token.from.keychain')
  })

  it('treats a null from the store as no token', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue(null)

    await hydrateToken()

    expect(getToken()).toBeNull()
  })

  it('treats an undefined from the store as no token, not the string "undefined"', async () => {
    // A Tauri version could serialize Rust `None` as `undefined` rather than
    // `null`; both must resolve to no token, keeping the `string | null`
    // contract getToken advertises.
    enterDesktopShell()
    invoke.mockResolvedValue(undefined)

    await hydrateToken()

    expect(getToken()).toBeNull()
  })

  it('persists the token to the OS credential store and never to localStorage', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue(undefined)

    setToken('bearer.jwt.value')
    // getToken and the localStorage guarantee are synchronous; the native write
    // is dispatched on the persistence queue.
    expect(getToken()).toBe('bearer.jwt.value')
    // The security property ADR 0001 requires: no token in webview localStorage.
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()

    await credentialPersistenceSettled()
    expect(invoke).toHaveBeenCalledWith('credential_set', { token: 'bearer.jwt.value' })
  })

  it('clears the credential from the OS store on logout, leaving localStorage untouched', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue(undefined)

    setToken('bearer.jwt.value')
    setToken(null)
    expect(getToken()).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()

    await credentialPersistenceSettled()
    // Serialized in order: the set is dispatched before the clear, so the store
    // ends cleared.
    expect(invoke).toHaveBeenNthCalledWith(1, 'credential_set', { token: 'bearer.jwt.value' })
    expect(invoke).toHaveBeenLastCalledWith('credential_clear')
  })

  it('never writes a token to localStorage even when one was already there', () => {
    // A token left in localStorage by an earlier browser session must not be
    // treated as the shell's store, and the shell must not add to it.
    enterDesktopShell()
    invoke.mockResolvedValue(undefined)

    setToken('shell.token')

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })

  it('still clears the store when the preceding set failed', async () => {
    // A set that rejects (store momentarily locked) must not block the clear
    // queued after it, or a logout would leave the just-failed token behind.
    enterDesktopShell()
    invoke.mockImplementation((cmd: string) =>
      cmd === 'credential_set' ? Promise.reject(new Error('store locked')) : Promise.resolve(undefined),
    )

    setToken('bearer.jwt.value')
    setToken(null)

    // The failed set is swallowed rather than throwing out of the sync call.
    await expect(credentialPersistenceSettled()).resolves.toBeUndefined()
    expect(invoke).toHaveBeenNthCalledWith(1, 'credential_set', { token: 'bearer.jwt.value' })
    expect(invoke).toHaveBeenLastCalledWith('credential_clear')
  })
})

describe('credentialStore — clearToken surfaces failure', () => {
  it('resolves and removes the token in the browser build', async () => {
    localStorage.setItem(TOKEN_KEY, 'browser.token')

    await expect(clearToken()).resolves.toBeUndefined()

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(getToken()).toBeNull()
    expect(invoke).not.toHaveBeenCalled()
  })

  it('rejects when the OS store cannot be cleared, so logout can react', async () => {
    // The security-relevant case: the credential could not be removed. Unlike a
    // failed set, this must not be swallowed — a caller has to know the token
    // may still be in the store.
    enterDesktopShell()
    invoke.mockRejectedValue(new Error('secret service unavailable'))

    await expect(clearToken()).rejects.toThrow('secret service unavailable')
    // The in-memory session still ends immediately regardless.
    expect(getToken()).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })

  it('resolves when the OS store clears successfully', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue(undefined)

    await expect(clearToken()).resolves.toBeUndefined()
    expect(invoke).toHaveBeenCalledWith('credential_clear')
  })
})
