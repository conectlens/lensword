import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { settingsApi } from '../../lib/api'
import type { RecallSettings } from '../../lib/types'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { Toggle } from '../../components/ui/Toggle'

const INTENSITY_LABELS = ['', 'Gentle', 'Light', 'Balanced', 'Firm', 'Intense']

export function SettingsPage() {
  const { user } = useAuth()
  const [settings, setSettings] = useState<RecallSettings | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    settingsApi.getRecallSettings().then(setSettings)
  }, [])

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
