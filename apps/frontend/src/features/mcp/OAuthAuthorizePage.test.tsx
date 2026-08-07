import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { OAuthAuthorizePage } from './OAuthAuthorizePage'
import { AuthProvider } from '../../context/AuthContext'
import { authApi, mcpOauthApi } from '../../lib/api'
import { resetCredentialStoreForTests } from '../../lib/credentialStore'
import type { McpAuthorizeDecision, McpAuthorizePreview, User } from '../../lib/types'

vi.mock('../../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api')>()
  return {
    ...actual,
    authApi: { ...actual.authApi, me: vi.fn() },
    mcpOauthApi: { ...actual.mcpOauthApi, authorize: vi.fn(), decide: vi.fn() },
  }
})

const me = vi.mocked(authApi.me)
const authorize = vi.mocked(mcpOauthApi.authorize)
const decide = vi.mocked(mcpOauthApi.decide)

const AUTHORIZE_QUERY =
  '/oauth/authorize?response_type=code&client_id=lwmcp_client_abc&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback' +
  '&code_challenge=XGs89fE2d5AjLtZfdLwNh6AqdRPjIxiVilxaymaTGhU&code_challenge_method=S256&state=xyz&scope=vocabulary-read+session-read'

function user(over: Partial<User> = {}): User {
  return {
    id: 1, username: 'alex', email: 'alex@example.com', role: 'user', created_at: '2026-08-01T00:00:00',
    streak_days: 0, longest_streak_days: 0, last_activity_date: null, total_words_learned: 0, total_study_seconds: 0,
    ...over,
  } as User
}

function preview(over: Partial<McpAuthorizePreview> = {}): McpAuthorizePreview {
  return {
    client_id: 'lwmcp_client_abc', client_name: 'Claude', redirect_uri: 'https://claude.ai/api/mcp/auth_callback',
    workspace: 'production', scopes: ['vocabulary-read', 'session-read'],
    already_granted_scopes: [], new_scopes: ['vocabulary-read', 'session-read'],
    ...over,
  }
}

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location">{location.pathname + location.search}</span>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/oauth/authorize" element={<OAuthAuthorizePage />} />
          <Route path="/login" element={<LocationProbe />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const originalLocation = window.location

beforeEach(() => {
  localStorage.clear()
  resetCredentialStoreForTests()
  me.mockReset()
  authorize.mockReset()
  decide.mockReset()
  // jsdom's window.location isn't reassignable directly (read-only own
  // property) and TypeScript rejects a plain `=` here regardless;
  // redefine the property itself instead.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...originalLocation, href: '' },
  })
})

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
})

describe('not logged in', () => {
  it('redirects to login, preserving this URL as ?next=', async () => {
    me.mockRejectedValue(new Error('no session'))

    renderAt(AUTHORIZE_QUERY)

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'))
    const next = new URLSearchParams(screen.getByTestId('location').textContent!.split('?')[1]).get('next')
    expect(next).toBe(AUTHORIZE_QUERY)
    expect(authorize).not.toHaveBeenCalled()
  })
})

describe('a malformed request', () => {
  it('shows an error instead of calling the API when required params are missing', async () => {
    me.mockResolvedValue(user())
    localStorage.setItem('lensword_token', 'a.b.c')

    renderAt('/oauth/authorize?client_id=lwmcp_client_abc')

    await waitFor(() => expect(screen.getByText('Invalid connection request')).toBeInTheDocument())
    expect(authorize).not.toHaveBeenCalled()
  })
})

describe('logged in with a well-formed request', () => {
  beforeEach(() => {
    me.mockResolvedValue(user())
    localStorage.setItem('lensword_token', 'a.b.c')
  })

  it('fetches and renders the consent preview', async () => {
    authorize.mockResolvedValue(preview())

    renderAt(AUTHORIZE_QUERY)

    await waitFor(() => expect(screen.getByText('Connect Claude to LensWord')).toBeInTheDocument())
    expect(screen.getByText('Read your vocabulary')).toBeInTheDocument()
    expect(screen.getByText('Read your study sessions')).toBeInTheDocument()
    expect(authorize).toHaveBeenCalledWith(
      expect.objectContaining({ client_id: 'lwmcp_client_abc', scope: 'vocabulary-read session-read' }),
    )
  })

  it('marks scopes already granted in a prior connection', async () => {
    authorize.mockResolvedValue(preview({ already_granted_scopes: ['vocabulary-read'] }))

    renderAt(AUTHORIZE_QUERY)

    await waitFor(() => expect(screen.getAllByText('already granted')).toHaveLength(1))
  })

  it('approving posts the decision with the preview-resolved workspace and navigates to redirect_uri', async () => {
    authorize.mockResolvedValue(preview({ workspace: 'production' }))
    const decision: McpAuthorizeDecision = { redirect_uri: 'https://claude.ai/api/mcp/auth_callback?code=abc&state=xyz' }
    decide.mockResolvedValue(decision)

    renderAt(AUTHORIZE_QUERY)
    await waitFor(() => expect(screen.getByText('Connect Claude to LensWord')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))

    await waitFor(() => expect(window.location.href).toBe(decision.redirect_uri))
    expect(decide).toHaveBeenCalledWith(
      expect.objectContaining({ client_id: 'lwmcp_client_abc', workspace: 'production', approve: true }),
    )
  })

  it('denying posts approve: false and still navigates to redirect_uri', async () => {
    authorize.mockResolvedValue(preview())
    const decision: McpAuthorizeDecision = { redirect_uri: 'https://claude.ai/api/mcp/auth_callback?error=access_denied&state=xyz' }
    decide.mockResolvedValue(decision)

    renderAt(AUTHORIZE_QUERY)
    await waitFor(() => expect(screen.getByText('Connect Claude to LensWord')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Deny' }))

    await waitFor(() => expect(window.location.href).toBe(decision.redirect_uri))
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ approve: false }))
  })
})
