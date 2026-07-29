import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { aiSettingsApi, settingsApi } from '../../lib/api'
import type { AISettings, RecallSettings } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { Toggle } from '../../components/ui/Toggle'

const INTENSITY_LABELS = ['', 'Gentle', 'Light', 'Balanced', 'Firm', 'Intense']

export function SettingsPage() {
  const { user } = useAuth()
  const [settings, setSettings] = useState<RecallSettings | null>(null)
  const [saved, setSaved] = useState(false)
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null)

  useEffect(() => {
    settingsApi.getRecallSettings().then(setSettings)
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

      {user?.role === 'admin' && aiSettings && (
        <AISettingsCard
          settings={aiSettings}
          onSave={async (next) => setAiSettings(await aiSettingsApi.update(next))}
        />
      )}

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
