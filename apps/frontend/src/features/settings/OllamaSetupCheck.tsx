import { useState } from 'react'
import { aiSettingsApi } from '../../lib/api'
import type { OllamaProbe } from '../../lib/types'
import { Button } from '../../components/ui/Button'

/**
 * Checking whether Ollama is actually usable (issue #139).
 *
 * The value of a detection step is that it says what to do next. "AI
 * unavailable" is something the user could already see; it does not
 * distinguish a daemon that is not running from one that is running with no
 * model pulled, and those need completely different fixes.
 *
 * So the wording comes from the server, where the check happened, rather than
 * being reconstructed here from a boolean — a UI that composed its own message
 * would drift out of agreement with what was actually observed.
 */

const TONE: Record<'ready' | 'partial' | 'down', string> = {
  ready: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
  // Reachable but not usable. Deliberately not the same colour as "down":
  // there is something to fix here and it is nearly working.
  partial: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
  down: 'border-red-400/30 bg-red-400/10 text-red-100',
}

function toneOf(probe: OllamaProbe): keyof typeof TONE {
  if (probe.ready) return 'ready'
  return probe.reachable ? 'partial' : 'down'
}

export function OllamaSetupCheck() {
  const [probe, setProbe] = useState<OllamaProbe | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function check() {
    setBusy(true)
    setFailed(false)
    try {
      setProbe(await aiSettingsApi.probe())
    } catch {
      setFailed(true)
      setProbe(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Button size="sm" variant="secondary" loading={busy} onClick={() => void check()}>
          Check Ollama
        </Button>
        <span className="text-sm text-white/40">
          Reports whether the daemon is reachable and the configured model is installed.
        </span>
      </div>

      {failed && (
        <p role="alert" className="text-sm text-red-300">
          Could not run the check.
        </p>
      )}

      {probe && (
        <div role="status" className={`rounded-lg border p-3 text-sm ${TONE[toneOf(probe)]}`}>
          <p>{probe.detail}</p>

          {/* Shown only when there is nothing installed at all. Suggesting a
              pull to someone who already has models would be noise. */}
          {probe.reachable && probe.models.length === 0 && (
            <p className="mt-2 font-mono text-xs">ollama pull {probe.recommended_model}</p>
          )}

          {probe.models.length > 0 && (
            <p className="mt-2 text-xs opacity-80">Installed: {probe.models.join(', ')}</p>
          )}
        </div>
      )}
    </div>
  )
}
