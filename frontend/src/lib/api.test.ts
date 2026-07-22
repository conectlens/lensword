import { describe, expect, it, beforeEach } from 'vitest'
import { getToken, setToken } from './api'

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
