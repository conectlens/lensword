import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { aiSettingsApi, practiceApi, settingsApi } from '../../lib/api'
import type { AISettings, DailySession, RecallSettings } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { Toggle } from '../../components/ui/Toggle'
import { connectMcpServer, deleteMcpServer, disconnectMcpServer, isMcpDesktopAvailable, listMcpServers, saveMcpServer } from '../../lib/mcpClient'
import type { McpServer, McpServerSave } from '../../lib/mcpClient'

const INTENSITY_LABELS = ['', 'Gentle', 'Light', 'Balanced', 'Firm', 'Intense']

export function SettingsPage() {
  const { user } = useAuth()
  const [settings, setSettings] = useState<RecallSettings | null>(null)
  const [saved, setSaved] = useState(false)
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null)
  const [dailySession, setDailySession] = useState<DailySession | null>(null)

  useEffect(() => {
    settingsApi.getRecallSettings().then(setSettings)
    practiceApi.dailySession().then(setDailySession)
    if (user?.role === 'admin') aiSettingsApi.get().then(setAiSettings).catch(() => setAiSettings(null))
  }, [user?.role])

  async function save(next: RecallSettings) {
    setSettings(next)
    const result = await settingsApi.updateRecallSettings(next)
    setSettings(result)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  function patch(partial: Partial<RecallSettings>) {
    if (!settings) return
    save({ ...settings, ...partial })
  }

  if (!settings) return <Spinner />

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-3xl font-bold text-white">Settings</h1>
        {saved && <span className="text-sm text-success">Saved</span>}
      </div>

      <Card className="p-6">
        <h2 className="mb-4 font-display text-lg font-bold text-white">Account</h2>
        <div className="flex items-center justify-between border-b border-white/10 py-3">
          <div className="flex items-center gap-3 text-white/70">
            <Icon name="mail" /> Email
          </div>
          <span className="text-white/50">{user?.email}</span>
        </div>
      </Card>

      {dailySession && <Card className="p-6">
        <div className="flex items-center justify-between">
          <div><h2 className="font-display text-lg font-bold text-white">Daily practice session</h2><p className="text-sm text-white/50">Set a realistic daily target for your adaptive review queue.</p></div>
          <Toggle checked={dailySession.enabled} onChange={async (enabled) => setDailySession(await practiceApi.updateDailySession({ ...dailySession, enabled }))} />
        </div>
        <label className="mt-4 flex flex-col gap-1 text-sm text-white/70">Daily goal (minutes)
          <input aria-label="Daily goal minutes" type="number" min={1} max={180} value={dailySession.goal_minutes} onChange={async (event) => setDailySession(await practiceApi.updateDailySession({ ...dailySession, goal_minutes: Number(event.target.value) }))} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="mt-4 flex flex-col gap-1 text-sm text-white/70">Daily review limit
          <input aria-label="Daily review limit" type="number" min={1} max={100} value={dailySession.review_limit} onChange={async (event) => setDailySession(await practiceApi.updateDailySession({ ...dailySession, review_limit: Number(event.target.value) }))} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
      </Card>}

      {user?.role === 'admin' && aiSettings && (
        <AISettingsCard
          settings={aiSettings}
          onSave={async (next) => setAiSettings(await aiSettingsApi.update(next))}
        />
      )}

      <McpServersCard />

      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="font-display text-lg font-bold text-white">Forced Recall Engine</h2>
            <p className="text-sm text-white/50">Interrupts you with micro-questions to strengthen retention.</p>
          </div>
          <Toggle checked={settings.enabled} onChange={(enabled) => patch({ enabled })} />
        </div>

        <div className="mb-6">
          <p className="mb-2 text-sm font-medium text-white">Intensity — {INTENSITY_LABELS[settings.intensity]}</p>
          <input
            type="range"
            min={1}
            max={5}
            value={settings.intensity}
            onChange={(e) => patch({ intensity: Number(e.target.value) })}
            className="w-full accent-primary"
          />
          <div className="mt-1 flex justify-between text-xs text-white/40">
            <span>Gentle</span>
            <span>Intense</span>
          </div>
        </div>

        <label className="mb-4 flex flex-col gap-1 text-sm text-white/70">
          Review scheduler
          <select
            aria-label="Review scheduler"
            value={settings.scheduler}
            onChange={(event) => patch({ scheduler: event.target.value as RecallSettings['scheduler'] })}
            className="rounded-lg bg-white/5 px-3 py-2 text-white"
          >
            <option value="sm2">SM-2 (classic)</option>
            <option value="fsrs">FSRS (adaptive)</option>
          </select>
          <span className="text-xs text-white/40">FSRS schedules each next review from its estimated retrievability.</span>
        </label>

        <div className="flex flex-col divide-y divide-white/10">
          <ToggleRow
            icon="wb_sunny"
            title="Morning check-in"
            description="Kickstart your day with a quick review."
            checked={settings.morning_checkin_enabled}
            onChange={(v) => patch({ morning_checkin_enabled: v })}
          />
          <ToggleRow
            icon="hourglass_empty"
            title="Idle time"
            description="Recalls when you seem to be taking a break."
            checked={settings.idle_time_enabled}
            onChange={(v) => patch({ idle_time_enabled: v })}
          />
          <ToggleRow
            icon="directions_walk"
            title="Walking mode"
            description="Multiple-choice recalls while you're on the move."
            checked={settings.walking_mode_enabled}
            onChange={(v) => patch({ walking_mode_enabled: v })}
          />
          <ToggleRow
            icon="school"
            title="Study breaks"
            description="Review words between study sessions."
            checked={settings.study_breaks_enabled}
            onChange={(v) => patch({ study_breaks_enabled: v })}
          />
          <ToggleRow
            icon="bedtime"
            title="Night wind-down"
            description="A final, gentle recall before sleep."
            checked={settings.night_winddown_enabled}
            onChange={(v) => patch({ night_winddown_enabled: v })}
          />
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="mb-4 font-display text-lg font-bold text-white">Notifications</h2>
        <p className="mb-4 text-sm text-white/40">
          These preferences are saved, but actual push/email/desktop delivery isn&apos;t wired to a notification provider in this build —
          see the README.
        </p>
        <div className="flex flex-col divide-y divide-white/10">
          <ToggleRow icon="phone_iphone" title="Mobile push" description="" checked={settings.push_enabled} onChange={(v) => patch({ push_enabled: v })} />
          <ToggleRow icon="mail" title="Email summary" description="" checked={settings.email_enabled} onChange={(v) => patch({ email_enabled: v })} />
          <ToggleRow icon="desktop_windows" title="Desktop browser" description="" checked={settings.desktop_enabled} onChange={(v) => patch({ desktop_enabled: v })} />
          <ToggleRow icon="notifications_active" title="In-app popups" description="" checked={settings.in_app_enabled} onChange={(v) => patch({ in_app_enabled: v })} />
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="mb-4 font-display text-lg font-bold text-white">Time zone</h2>
        <p className="mb-4 text-sm text-white/40">
          Reminder times and quiet hours are read on this clock. Set it to where you actually are, or reminders arrive at the
          wrong hour.
        </p>
        <TimeZoneSelect value={settings.time_zone} onChange={(v) => patch({ time_zone: v })} />
      </Card>
    </div>
  )
}

const EMPTY_MCP_SERVER: McpServerSave = {
  id: '', name: '', command: '', args: [], enabled: true, workspaceRoots: [], allowedTools: [], timeoutMs: 10_000,
}

function McpServersCard() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [draft, setDraft] = useState<McpServerSave>(EMPTY_MCP_SERVER)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const desktop = isMcpDesktopAvailable()

  async function refresh() {
    try { setServers(await listMcpServers()) } catch (err) { setError(err instanceof Error ? err.message : 'Could not load MCP connections.') }
  }
  useEffect(() => { if (desktop) void refresh() }, [desktop])
  if (!desktop) return null

  async function save() {
    try {
      setBusy(true); setError(null)
      await saveMcpServer(draft)
      setDraft(EMPTY_MCP_SERVER)
      await refresh()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save the MCP server.') } finally { setBusy(false) }
  }

  async function withServer(action: () => Promise<void>) {
    try { setBusy(true); setError(null); await action(); await refresh() } catch (err) { setError(err instanceof Error ? err.message : 'MCP server operation failed.') } finally { setBusy(false) }
  }

  return <Card className="p-6">
    <h2 className="font-display text-lg font-bold text-white">MCP connections</h2>
    <p className="mt-1 text-sm text-white/50">Local stdio servers run outside the webview. Their definitions and optional credentials are stored in your operating system&apos;s credential store.</p>
    <div className="mt-5 space-y-3">
      {servers.map((server) => <div key={server.id} className="rounded-lg border border-white/10 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-medium text-white">{server.name} <span className="text-xs text-white/40">{server.identity && `· ${server.identity}`}</span></p><p className="text-xs text-white/50">{server.tools.map((tool) => tool.name).join(', ') || 'No approved tools discovered yet'}</p></div><span className={`text-xs ${server.health === 'connected' ? 'text-success' : 'text-white/50'}`}>{server.health}</span></div>
        {server.capabilityChanged && <p className="mt-2 text-xs text-warning">Server capabilities changed; newly discovered tools remain blocked until you explicitly allow them.</p>}
        <div className="mt-3 flex gap-2"><Button disabled={busy || !server.enabled} onClick={() => withServer(() => connectMcpServer(server.id).then(() => undefined))}>{server.health === 'connected' ? 'Reconnect' : 'Connect'}</Button>{server.health === 'connected' && <Button disabled={busy} onClick={() => withServer(() => disconnectMcpServer(server.id))}>Disconnect</Button>}<Button disabled={busy} onClick={() => withServer(() => deleteMcpServer(server.id))}>Remove</Button></div>
      </div>)}
    </div>
    <div className="mt-5 grid gap-3 border-t border-white/10 pt-5 sm:grid-cols-2">
      <label className="text-sm text-white/70">Name<input aria-label="MCP server name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">ID<input aria-label="MCP server ID" value={draft.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70 sm:col-span-2">Command<input aria-label="MCP server command" value={draft.command} onChange={(e) => setDraft({ ...draft, command: e.target.value })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Arguments (space-separated)<input aria-label="MCP server arguments" value={draft.args.join(' ')} onChange={(e) => setDraft({ ...draft, args: e.target.value.split(/\s+/).filter(Boolean) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Allowed tools (comma-separated)<input aria-label="MCP allowed tools" value={draft.allowedTools.join(', ')} onChange={(e) => setDraft({ ...draft, allowedTools: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70 sm:col-span-2">Approved workspace roots (comma-separated absolute paths)<input aria-label="MCP workspace roots" value={draft.workspaceRoots.join(', ')} onChange={(e) => setDraft({ ...draft, workspaceRoots: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Credential (optional)<input aria-label="MCP server credential" type="password" value={draft.credential ?? ''} onChange={(e) => setDraft({ ...draft, credential: e.target.value || undefined })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
      <label className="text-sm text-white/70">Timeout (milliseconds)<input aria-label="MCP timeout" type="number" min={250} max={120000} value={draft.timeoutMs} onChange={(e) => setDraft({ ...draft, timeoutMs: Number(e.target.value) })} className="mt-1 w-full rounded-lg bg-white/5 px-3 py-2 text-white" /></label>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
    <div className="mt-4"><Button disabled={busy} onClick={save}>Save MCP server</Button></div>
  </Card>
}

export function AISettingsCard({ settings, onSave }: { settings: AISettings; onSave: (settings: AISettings) => Promise<void> }) {
  const [draft, setDraft] = useState(settings)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => setDraft(settings), [settings])

  async function saveAiSettings() {
    if (!draft.model.trim()) return setError('Model is required.')
    try {
      const url = new URL(draft.base_url)
      if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error()
    } catch {
      return setError('Base URL must be a valid HTTP or HTTPS URL.')
    }
    if (draft.max_output_tokens <= 0 || draft.context_max_chars <= 0) {
      return setError('Maximum tokens and context length must be greater than zero.')
    }
    try {
      setError(null)
      await onSave(draft)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save AI settings.')
    }
  }

  return (
    <Card className="p-6">
      <h2 className="font-display text-lg font-bold text-white">AI provider</h2>
      <p className="mt-1 text-sm text-white/50">Deployment-wide configuration. Only administrators can change these values.</p>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm text-white/70">Provider
          <select aria-label="AI provider" value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value as AISettings['provider'] })} className="rounded-lg bg-white/5 px-3 py-2 text-white">
            <option value="none">Disabled</option>
            <option value="ollama">Ollama</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70">Model
          <input aria-label="AI model" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70 sm:col-span-2">Base URL
          <input aria-label="AI base URL" value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70">Maximum output tokens
          <input aria-label="Maximum output tokens" type="number" min={1} value={draft.max_output_tokens} onChange={(e) => setDraft({ ...draft, max_output_tokens: Number(e.target.value) })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
        <label className="flex flex-col gap-1 text-sm text-white/70">Context length
          <input aria-label="Context length" type="number" min={1} value={draft.context_max_chars} onChange={(e) => setDraft({ ...draft, context_max_chars: Number(e.target.value) })} className="rounded-lg bg-white/5 px-3 py-2 text-white" />
        </label>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      <div className="mt-5 flex items-center gap-3"><Button onClick={saveAiSettings}>Save AI settings</Button>{saved && <span className="text-sm text-success">Saved</span>}</div>
    </Card>
  )
}

/** Detected from the browser, used as the suggestion for an account that has
 *  never chosen one. Falls back to UTC where the API is unavailable. */
function detectedTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

function TimeZoneSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  // Intl.supportedValuesOf is unavailable on older engines; the list then
  // narrows to the values that matter here rather than the control vanishing.
  const zones = useMemo(() => {
    const all =
      typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []
    return Array.from(new Set(['UTC', detectedTimeZone(), value, ...all])).filter(Boolean).sort()
  }, [value])

  const detected = detectedTimeZone()

  return (
    <div className="flex flex-col gap-2">
      <select
        aria-label="Time zone"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white outline-none focus:border-white/30"
      >
        {zones.map((zone) => (
          <option key={zone} value={zone} className="bg-slate-900">
            {zone}
          </option>
        ))}
      </select>
      {value !== detected && (
        <button
          type="button"
          onClick={() => onChange(detected)}
          className="self-start text-xs text-white/50 underline underline-offset-2 hover:text-white/80"
        >
          Use detected time zone ({detected})
        </button>
      )}
    </div>
  )
}

function ToggleRow({ icon, title, description, checked, onChange }: { icon: string; title: string; description: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between py-3">
      <div className="flex items-center gap-3">
        <Icon name={icon} className="text-primary" />
        <div>
          <p className="font-medium text-white">{title}</p>
          {description && <p className="text-sm text-white/40">{description}</p>}
        </div>
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  )
}
