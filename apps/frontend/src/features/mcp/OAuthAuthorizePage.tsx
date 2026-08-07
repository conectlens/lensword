import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { ApiRequestError, mcpOauthApi } from '../../lib/api'
import type { McpAuthorizePreview, McpAuthorizeRequest } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

const SCOPE_LABELS: Record<string, string> = {
  'profile-read': 'Read your profile',
  'vocabulary-read': 'Read your vocabulary',
  'session-read': 'Read your study sessions',
  'progress-read': 'Read your learning progress',
  'conversation-write': 'Start and reply in AI conversations on your behalf',
  'review-write': 'Record review answers on your behalf',
  'card-write': 'Add or edit vocabulary cards on your behalf',
  'context-import': 'Import context you send it into your vocabulary',
}

function scopeLabel(scope: string): string {
  return SCOPE_LABELS[scope] ?? scope
}

/** Reads the OAuth params a connector (e.g. Claude.ai) redirected the
 * browser here with. `workspace` is deliberately not among them — see
 * McpAuthorizeRequest's docstring; the backend resolves it and this page
 * only ever echoes back what GET /authorize returns. */
function readAuthorizeRequest(searchParams: URLSearchParams): McpAuthorizeRequest | null {
  const client_id = searchParams.get('client_id')
  const redirect_uri = searchParams.get('redirect_uri')
  const scope = searchParams.get('scope')
  if (!client_id || !redirect_uri || !scope) return null
  return {
    response_type: searchParams.get('response_type') ?? 'code',
    client_id,
    redirect_uri,
    code_challenge: searchParams.get('code_challenge') ?? '',
    code_challenge_method: searchParams.get('code_challenge_method') ?? '',
    scope,
    state: searchParams.get('state') ?? '',
  }
}

export function OAuthAuthorizePage() {
  const { user, loading: authLoading } = useAuth()
  const [searchParams] = useSearchParams()
  const [preview, setPreview] = useState<McpAuthorizePreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deciding, setDeciding] = useState(false)

  const request = readAuthorizeRequest(searchParams)

  useEffect(() => {
    if (!user || !request) return
    let cancelled = false
    setError(null) // eslint-disable-line react-hooks/set-state-in-effect -- clears a previous attempt's error before this one starts, same pattern as RemoteCompanionsCard's refresh()
    mcpOauthApi
      .authorize(request)
      .then((result) => {
        if (!cancelled) setPreview(result)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiRequestError ? err.message : 'Could not load this connection request.')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- request is derived fresh from searchParams every render; keying on its fields (not the object) avoids refetching on every render
  }, [user, request?.client_id, request?.redirect_uri, request?.scope, request?.state])

  if (authLoading) return <Spinner />
  if (!user) {
    const next = `/oauth/authorize?${searchParams.toString()}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }

  if (!request) {
    return (
      <CenteredCard>
        <Icon name="error" className="text-4xl text-danger" />
        <h1 className="font-display text-2xl font-bold text-white">Invalid connection request</h1>
        <p className="text-center text-white/50">
          This link is missing information a connection request needs (client, redirect, or scope). Ask
          whatever app sent you here to try connecting again.
        </p>
      </CenteredCard>
    )
  }

  async function decide(approve: boolean) {
    if (!preview) return
    setDeciding(true)
    setError(null)
    try {
      const result = await mcpOauthApi.decide({ ...request!, workspace: preview.workspace, approve })
      // A full navigation, not client-side routing: redirect_uri hands off
      // to the external connector's own callback (e.g. claude.ai), which is
      // not a route this app owns.
      window.location.href = result.redirect_uri
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : 'Could not complete this request. Please try again.')
      setDeciding(false)
    }
  }

  if (error && !preview) {
    return (
      <CenteredCard>
        <Icon name="error" className="text-4xl text-danger" />
        <h1 className="font-display text-2xl font-bold text-white">Something went wrong</h1>
        <p className="text-center text-white/50">{error}</p>
      </CenteredCard>
    )
  }

  if (!preview) {
    return (
      <CenteredCard>
        <Spinner />
      </CenteredCard>
    )
  }

  return (
    <CenteredCard>
      <Icon name="link" className="text-4xl text-primary" />
      <h1 className="font-display text-2xl font-bold text-white text-center">
        Connect {preview.client_name} to LensWord
      </h1>
      <p className="text-center text-white/50">
        Signed in as <span className="text-white/80">{user.username}</span>. {preview.client_name} is asking
        for permission to:
      </p>
      <ul className="flex w-full flex-col gap-2">
        {preview.scopes.map((scope) => (
          <li key={scope} className="flex items-center gap-2 rounded-lg border border-white/10 p-3 text-sm text-white/80">
            <Icon
              name={preview.already_granted_scopes.includes(scope) ? 'check_circle' : 'radio_button_unchecked'}
              className={preview.already_granted_scopes.includes(scope) ? 'text-success' : 'text-white/40'}
            />
            {scopeLabel(scope)}
            {preview.already_granted_scopes.includes(scope) && (
              <span className="ml-auto text-xs text-white/40">already granted</span>
            )}
          </li>
        ))}
      </ul>
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="flex w-full gap-3">
        <Button variant="secondary" className="flex-1" disabled={deciding} onClick={() => decide(false)}>
          Deny
        </Button>
        <Button variant="primary" className="flex-1" loading={deciding} onClick={() => decide(true)}>
          Allow
        </Button>
      </div>
    </CenteredCard>
  )
}

function CenteredCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen w-full flex-col items-center justify-center bg-canvas-dark p-4">
      <Card className="flex w-full max-w-md flex-col items-center gap-4 p-8">{children}</Card>
    </div>
  )
}
