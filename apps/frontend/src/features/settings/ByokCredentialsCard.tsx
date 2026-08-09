import { useEffect, useState } from 'react'
import { aiCredentialsApi, ApiRequestError } from '../../lib/api'
import type { ByokProvider, UserAICredentialSummary } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Select } from '../../components/ui/Select'

/**
 * Bring-Your-Own-Key AI credentials.
 *
 * The cloud deployment has no billing/credits system, so it cannot pay for
 * everyone's AI usage — this lets a user supply their own Gemini/OpenAI/
 * Vertex AI key for their own requests instead, used automatically in
 * place of the deployment's own AI provider (see
 * app.api.deps.resolve_ai_provider_for_user's docstring for the exact
 * precedence when someone has more than one configured).
 *
 * Every field below is write-only by design: the server never echoes a
 * submitted key back (GET reports only non-secret details, e.g. Vertex's
 * project/location), so there is nothing to pre-fill a form with — saving
 * again always means typing the value in again, the same shape the MCP
 * connection credential field on this page already uses.
 */

const PROVIDERS: { id: ByokProvider; label: string }[] = [
  { id: 'gemini', label: 'Gemini' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'vertex', label: 'Vertex AI' },
]

function labelFor(provider: ByokProvider): string {
  return PROVIDERS.find((p) => p.id === provider)?.label ?? provider
}

function detailsSummary(credential: UserAICredentialSummary): string | null {
  const entries = Object.entries(credential.details)
  if (entries.length === 0) return null
  return entries.map(([key, value]) => `${key}: ${value}`).join(' · ')
}

export function ByokCredentialsCard() {
  const [credentials, setCredentials] = useState<UserAICredentialSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyProvider, setBusyProvider] = useState<ByokProvider | null>(null)

  const [provider, setProvider] = useState<ByokProvider>('gemini')
  const [apiKey, setApiKey] = useState('')
  const [serviceAccountJson, setServiceAccountJson] = useState('')
  const [projectId, setProjectId] = useState('')
  const [location, setLocation] = useState('us-central1')

  async function refresh() {
    try {
      setCredentials(await aiCredentialsApi.list())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load your AI credentials.')
    }
  }

  useEffect(() => { void refresh() }, []) // eslint-disable-line react-hooks/set-state-in-effect

  function resetForm() {
    setApiKey('')
    setServiceAccountJson('')
    setProjectId('')
    setLocation('us-central1')
  }

  async function save() {
    const payload =
      provider === 'vertex'
        ? ({ service_account_json: serviceAccountJson, project_id: projectId, location } as Record<string, string>)
        : ({ api_key: apiKey } as Record<string, string>)

    try {
      setError(null)
      setBusyProvider(provider)
      await aiCredentialsApi.put(provider, payload)
      resetForm()
      await refresh()
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not save that credential.',
      )
    } finally {
      setBusyProvider(null)
    }
  }

  async function remove(target: ByokProvider) {
    try {
      setError(null)
      setBusyProvider(target)
      await aiCredentialsApi.remove(target)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove that credential.')
    } finally {
      setBusyProvider(null)
    }
  }

  if (!credentials) return null

  const canSave = provider === 'vertex' ? Boolean(serviceAccountJson.trim() && projectId.trim() && location.trim()) : Boolean(apiKey.trim())

  return (
    <Card className="p-6">
      <h2 className="font-display text-lg font-bold text-white">Your own AI key</h2>
      <p className="mt-1 text-sm text-white/50">
        This server does not bill you for AI usage — it also cannot pay for yours. Add your own Gemini, OpenAI, or
        Vertex AI key here and it is used for your own requests automatically, in place of whatever this deployment
        is otherwise configured with. Stored encrypted; never shown again after you save it.
      </p>

      {credentials.length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          {credentials.map((credential) => (
            <div
              key={credential.provider}
              className="flex items-center justify-between rounded-lg border border-white/10 p-3 text-sm"
            >
              <div>
                <p className="text-white">{labelFor(credential.provider)}</p>
                {detailsSummary(credential) && (
                  <p className="mt-1 text-xs text-white/50">{detailsSummary(credential)}</p>
                )}
              </div>
              <Button
                size="sm"
                variant="secondary"
                loading={busyProvider === credential.provider}
                onClick={() => void remove(credential.provider)}
              >
                Remove
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="mt-5 flex flex-col gap-3 border-t border-white/10 pt-5">
        <label className="flex flex-col gap-1 text-sm text-white/70">
          Provider
          <Select
            size="sm"
            aria-label="BYOK provider"
            value={provider}
            onValueChange={(next) => setProvider(next as ByokProvider)}
            options={PROVIDERS.map((p) => ({ value: p.id, label: p.label }))}
          />
        </label>

        {provider === 'vertex' ? (
          <>
            <label className="flex flex-col gap-1 text-sm text-white/70">
              Service account JSON
              <textarea
                aria-label="Vertex AI service account JSON"
                value={serviceAccountJson}
                onChange={(event) => setServiceAccountJson(event.target.value)}
                rows={4}
                placeholder="Paste the full contents of your service-account key file"
                className="rounded-lg bg-white/5 px-3 py-2 font-mono text-xs text-white"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-white/70">
              GCP project ID
              <input
                aria-label="Vertex AI project ID"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                className="rounded-lg bg-white/5 px-3 py-2 text-white"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-white/70">
              Location
              <input
                aria-label="Vertex AI location"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                className="rounded-lg bg-white/5 px-3 py-2 text-white"
              />
            </label>
          </>
        ) : (
          <label className="flex flex-col gap-1 text-sm text-white/70">
            API key
            <input
              aria-label={`${labelFor(provider)} API key`}
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              className="rounded-lg bg-white/5 px-3 py-2 text-white"
            />
          </label>
        )}

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}

        <div>
          <Button disabled={!canSave} loading={busyProvider === provider} onClick={() => void save()}>
            Save credential
          </Button>
        </div>
      </div>
    </Card>
  )
}
