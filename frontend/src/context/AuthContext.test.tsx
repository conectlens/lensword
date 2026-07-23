import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider, useAuth } from './AuthContext'
import { ApiRequestError, getToken, setToken } from '../lib/api'
import { resetCredentialStoreForTests } from '../lib/credentialStore'

const me = vi.hoisted(() => vi.fn())
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return { ...actual, authApi: { ...actual.authApi, me } }
})

// The real credentialStore is used (only `me` is mocked above), so its shell
// path reaches for the Tauri client — mock it here as the other shell tests do.
const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

const webview = window as unknown as Record<string, unknown>
function enterDesktopShell(): void {
  webview.__TAURI_INTERNALS__ = {}
}

function Probe() {
  const { loading, user } = useAuth()
  return <span data-testid="state">{loading ? 'loading' : user ? user.username : 'anonymous'}</span>
}

async function renderSettled() {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  )
  await waitFor(() => expect(screen.getByTestId('state')).not.toHaveTextContent('loading'))
}

beforeEach(() => {
  localStorage.clear()
  me.mockReset()
  invoke.mockReset()
  resetCredentialStoreForTests()
})

afterEach(() => {
  delete webview.__TAURI_INTERNALS__
  vi.clearAllMocks()
})

describe('restoring a session at startup', () => {
  it('keeps the stored token when the endpoint configuration is rejected', async () => {
    // The desktop shell refuses an endpoint that is neither loopback nor HTTPS,
    // so `me()` can now reject for a reason that has nothing to do with the
    // credential. Discarding the token here would log the user out over a typo
    // in a config file, and still force a re-login once it was corrected.
    setToken('abc.def.ghi')
    me.mockRejectedValue(new Error('refusing plain http to remote host `api.example.com`'))

    await renderSettled()

    expect(getToken()).toBe('abc.def.ghi')
    expect(screen.getByTestId('state')).toHaveTextContent('anonymous')
  })

  it('keeps the stored token when the request fails in transport', async () => {
    setToken('abc.def.ghi')
    me.mockRejectedValue(new TypeError('Failed to fetch'))

    await renderSettled()

    expect(getToken()).toBe('abc.def.ghi')
  })

  it('discards the token when the server rejects the credential', async () => {
    setToken('expired.token')
    me.mockRejectedValue(new ApiRequestError(401, 'Not authenticated'))

    await renderSettled()

    expect(getToken()).toBeNull()
  })

  it('restores the user when the credential is accepted', async () => {
    setToken('abc.def.ghi')
    me.mockResolvedValue({ id: 1, username: 'ada', email: 'ada@example.com' })

    await renderSettled()

    expect(screen.getByTestId('state')).toHaveTextContent('ada')
    expect(getToken()).toBe('abc.def.ghi')
  })

  it('hydrates the token from the OS store before deciding the shell user is logged out', async () => {
    // In the desktop shell the token lives in the OS credential store, not
    // localStorage. Without the hydrate step, refreshUser would read no token
    // and force a re-login on every launch. This test fails if that hydrate is
    // removed — nothing else exercises the shell startup path.
    enterDesktopShell()
    invoke.mockResolvedValue('token.from.keychain')
    me.mockResolvedValue({ id: 2, username: 'grace', email: 'grace@example.com' })

    await renderSettled()

    expect(invoke).toHaveBeenCalledWith('credential_get')
    expect(screen.getByTestId('state')).toHaveTextContent('grace')
  })
})
