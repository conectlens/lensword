import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { authApi, getToken, setToken, ApiRequestError } from './api'

describe('token storage', () => {
  beforeEach(() => localStorage.clear())

  it('returns null when no token has been set', () => {
    expect(getToken()).toBeNull()
  })

  it('persists and retrieves a token', () => {
    setToken('abc.def.ghi')
    expect(getToken()).toBe('abc.def.ghi')
  })

  it('clears the token when set to null', () => {
    setToken('abc.def.ghi')
    setToken(null)
    expect(getToken()).toBeNull()
  })
})

describe('request', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  function respond(body: unknown, status = 200): void {
    fetchMock.mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => 'application/json' },
      json: async () => body,
    })
  }

  it('joins the resolved base URL and the path exactly once', async () => {
    // Without this, dropping the `await` on the base URL sends every request to
    // `[object Promise]/api/v1/...` and still passes lint, build and the suite.
    respond({ id: 1, username: 'x', email: 'x@example.com' })

    await authApi.me()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/v1/auth/me')
  })

  it('sends the stored token as a bearer credential', async () => {
    setToken('abc.def.ghi')
    respond({ id: 1, username: 'x', email: 'x@example.com' })

    await authApi.me()

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer abc.def.ghi')
  })

  it('raises ApiRequestError carrying the status on a rejected request', async () => {
    respond({ detail: 'Not authenticated' }, 401)

    await expect(authApi.me()).rejects.toBeInstanceOf(ApiRequestError)
    await expect(authApi.me()).rejects.toMatchObject({ status: 401 })
  })
})
