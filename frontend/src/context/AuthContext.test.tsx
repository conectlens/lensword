import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider, useAuth } from './AuthContext'
import { ApiRequestError, getToken, setToken } from '../lib/api'

const me = vi.hoisted(() => vi.fn())
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return { ...actual, authApi: { ...actual.authApi, me } }
})

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
})

afterEach(() => vi.clearAllMocks())

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
})
