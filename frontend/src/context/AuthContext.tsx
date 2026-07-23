import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { ApiRequestError, authApi, clearToken, getToken, hydrateToken, setToken } from '../lib/api'
import type { User } from '../lib/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  async function refreshUser() {
    // Load the token from its backing store (the OS credential store in the
    // desktop shell, localStorage in the browser) before reading it. In the
    // shell the token is not in localStorage, so skipping this would always see
    // none and force a re-login on every launch.
    await hydrateToken()
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await authApi.me()
      setUser(me)
    } catch (err) {
      // Only the server rejecting the credential invalidates it. A transport
      // failure, or the desktop shell refusing a misconfigured API endpoint,
      // says nothing about whether the token is still good — discarding it
      // there would log the user out over a typo in a config file and force a
      // re-login even after the endpoint is corrected.
      if (err instanceof ApiRequestError && (err.status === 401 || err.status === 403)) {
        // The server rejected the credential, so it is already worthless; if the
        // OS store cannot be cleared right now, a persisted-but-rejected token is
        // harmless. Still surface a failure rather than swallowing it.
        clearToken().catch((clearErr) => {
          console.error('could not clear the rejected credential from the OS store', clearErr)
        })
      }
      setUser(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshUser()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function login(email: string, password: string) {
    const res = await authApi.login(email, password)
    setToken(res.token.access_token)
    setUser(res.user)
  }

  async function register(username: string, email: string, password: string) {
    const res = await authApi.register(username, email, password)
    setToken(res.token.access_token)
    setUser(res.user)
  }

  async function logout() {
    // Clearing the credential from the OS store must not fail silently: a token
    // left behind would let the next launch re-authenticate this session on a
    // shared machine. Retry once for a store that was momentarily busy, then
    // surface the failure loudly. The in-memory session ends either way.
    try {
      await clearToken()
    } catch {
      try {
        await clearToken()
      } catch (err) {
        console.error(
          'logout could not remove the stored credential; it may persist in the OS credential store',
          err,
        )
      }
    }
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
