import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { groupsApi, settingsApi } from '../../lib/api'
import { LANGUAGES, type SupportedLanguage } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Icon } from '../../components/ui/Icon'

const TOTAL_STEPS = 4

export function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [languages, setLanguages] = useState<SupportedLanguage[]>([])
  const [intensity, setIntensity] = useState(3)
  const [groupName, setGroupName] = useState('')
  const [saving, setSaving] = useState(false)

  function toggleLanguage(lang: SupportedLanguage) {
    setLanguages((prev) => (prev.includes(lang) ? prev.filter((l) => l !== lang) : [...prev, lang]))
  }

  async function finish() {
    setSaving(true)
    try {
      const current = await settingsApi.getRecallSettings()
      await settingsApi.updateRecallSettings({ ...current, intensity })
      if (groupName.trim()) {
        await groupsApi.create(groupName.trim(), languages[0] ?? 'Spanish')
      }
    } finally {
      setSaving(false)
      navigate('/dashboard')
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas-dark p-4">
      <div className="w-full max-w-lg rounded-lg bg-surface p-8 shadow-soft">
        <p className="mb-6 text-center text-sm font-medium text-white/40">Step {step} of {TOTAL_STEPS}</p>

        {step === 1 && (
          <div className="flex flex-col gap-6">
            <div className="text-center">
              <h1 className="font-display text-2xl font-bold text-white">What languages are you learning?</h1>
              <p className="text-white/50">You can select more than one.</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {LANGUAGES.filter((l) => l !== 'Other').map((lang) => (
                <button
                  key={lang}
                  onClick={() => toggleLanguage(lang)}
                  className={`rounded-lg border p-3 text-sm font-medium transition-colors ${languages.includes(lang) ? 'border-primary bg-primary/20 text-primary' : 'border-white/10 text-white/70 hover:bg-white/5'}`}
                >
                  {lang}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-col items-center gap-6 text-center">
            <Icon name="memory" className="text-5xl text-primary" />
            <div>
              <h1 className="font-display text-2xl font-bold text-white">Tune your Forced Recall Engine</h1>
              <p className="text-white/50">How often should LensWord interrupt you to review?</p>
            </div>
            <div className="w-full">
              <input type="range" min={1} max={5} value={intensity} onChange={(e) => setIntensity(Number(e.target.value))} className="w-full accent-primary" />
              <div className="mt-1 flex justify-between text-xs text-white/40">
                <span>Gentle</span>
                <span>Balanced</span>
                <span>Intense</span>
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col items-center gap-6 text-center">
            <Icon name="style" className="text-5xl text-primary" />
            <div>
              <h1 className="font-display text-2xl font-bold text-white">Create your first group</h1>
              <p className="text-white/50">A named collection of words you want to learn. You can add words to it next.</p>
            </div>
            <input
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              placeholder="e.g., Everyday Spanish"
              className="h-12 w-full rounded-lg border border-white/10 bg-white/5 px-4 text-center text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
        )}

        {step === 4 && (
          <div className="flex flex-col items-center gap-4 text-center">
            <Icon name="celebration" className="text-5xl text-primary" />
            <h1 className="font-display text-2xl font-bold text-white">You&apos;re all set</h1>
            <p className="text-white/50">Head to your dashboard to add words and start your first review.</p>
          </div>
        )}

        <div className="mt-8 flex justify-between">
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(1, s - 1))} disabled={step === 1}>
            Previous
          </Button>
          {step < TOTAL_STEPS ? (
            <Button onClick={() => setStep((s) => s + 1)}>Next</Button>
          ) : (
            <Button onClick={finish} loading={saving}>
              Go to dashboard
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
