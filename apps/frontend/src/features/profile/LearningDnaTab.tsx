import { useEffect, useState } from 'react'
import { learningDnaApi } from '../../lib/api'
import type { EfficacyEstimate, ModalityPreference } from '../../lib/types'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Button } from '../../components/ui/Button'

/**
 * Learning DNA (issue #186 TODO 4): what LensWord has actually measured
 * about which techniques help this learner, in which context — never a
 * brain-type bar chart or a "you are a visual learner" verdict. Every card
 * below carries its own sample size and uncertainty, and the three-way
 * split (works well / works poorly / not enough evidence yet) exists so an
 * absence of evidence is never rendered as evidence of absence.
 *
 * Stated modality preference is shown in its own section, deliberately
 * never merged with the measured cards — see `intervention_efficacy.py`'s
 * `build_modality_insight` docstring for why the backend keeps them apart
 * too.
 */

const MODALITY_OPTIONS = ['text', 'audio', 'image', 'spatial', 'story'] as const

function classify(estimate: EfficacyEstimate): 'works_well' | 'works_poorly' | 'unproven' {
  if (estimate.status !== 'MEASURED' || estimate.effect === null) return 'unproven'
  return estimate.effect > 0 ? 'works_well' : 'works_poorly'
}

function contextLabel(estimate: EfficacyEstimate): string {
  const c = estimate.context
  return `${c.item_class} · ${c.modality} · ${c.horizon_days}-day`
}

export function LearningDnaTab() {
  const [estimates, setEstimates] = useState<EfficacyEstimate[] | null>(null)
  const [preference, setPreference] = useState<ModalityPreference | null>(null)
  const [failed, setFailed] = useState(false)
  const [savingPreference, setSavingPreference] = useState(false)

  useEffect(() => {
    Promise.all([learningDnaApi.efficacy(), learningDnaApi.modalityPreference()])
      .then(([efficacy, pref]) => {
        setEstimates(efficacy)
        setPreference(pref)
      })
      .catch(() => setFailed(true))
  }, [])

  async function statePreference(modality: string) {
    setSavingPreference(true)
    try {
      const saved = await learningDnaApi.setModalityPreference(modality)
      setPreference(saved)
    } finally {
      setSavingPreference(false)
    }
  }

  if (failed) {
    return (
      <Card className="p-6">
        <p className="text-white/60">Could not load your Learning DNA just now.</p>
      </Card>
    )
  }

  if (estimates === null) return <Spinner />

  const worksWell = estimates.filter((e) => classify(e) === 'works_well')
  const worksPoorly = estimates.filter((e) => classify(e) === 'works_poorly')
  const unproven = estimates.filter((e) => classify(e) === 'unproven')

  return (
    <div className="flex flex-col gap-6">
      <Card className="border border-yellow-500/30 bg-yellow-500/10 p-4">
        <p className="text-sm text-white/80">
          <span className="font-semibold text-white">Not a medical or cognitive assessment.</span> This page shows
          what LensWord has measured about how specific study techniques worked for you, in specific contexts —
          it is not a diagnosis of how you learn, and it never labels you as a fixed type of learner.
        </p>
      </Card>

      <div>
        <h2 className="mb-2 font-display text-xl font-bold text-white">What you say you like</h2>
        <p className="mb-3 text-sm text-white/50">
          Your stated preference, kept separate from what is measured below — liking a format and it measurably
          helping you are different things.
        </p>
        <Card className="flex flex-wrap items-center gap-2 p-4">
          <span className="text-sm text-white/70">
            {preference ? (
              <>
                You said you prefer <span className="font-semibold text-white">{preference.modality}</span>
              </>
            ) : (
              'You have not told us a preference yet.'
            )}
          </span>
          <span className="mx-2 h-4 w-px bg-white/10" />
          {MODALITY_OPTIONS.map((modality) => (
            <Button
              key={modality}
              size="sm"
              variant={preference?.modality === modality ? 'primary' : 'secondary'}
              disabled={savingPreference}
              onClick={() => statePreference(modality)}
            >
              {modality}
            </Button>
          ))}
        </Card>
      </div>

      <EfficacyGroup
        title="Works well for you"
        emptyHint="Nothing has a clear positive, well-evidenced effect yet."
        estimates={worksWell}
      />
      <EfficacyGroup
        title="Works poorly for you"
        emptyHint="Nothing has a clear negative, well-evidenced effect yet."
        estimates={worksPoorly}
      />
      <EfficacyGroup
        title="Not enough evidence yet"
        emptyHint="Everything measured so far has enough evidence to report."
        estimates={unproven}
      />
    </div>
  )
}

function EfficacyGroup({
  title,
  emptyHint,
  estimates,
}: {
  title: string
  emptyHint: string
  estimates: EfficacyEstimate[]
}) {
  return (
    <div>
      <h2 className="mb-3 font-display text-xl font-bold text-white">{title}</h2>
      {estimates.length === 0 ? (
        <Card className="p-4">
          <p className="text-sm text-white/50">{emptyHint}</p>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {estimates.map((estimate, index) => (
            <EfficacyCard key={`${estimate.intervention_type}-${index}`} estimate={estimate} />
          ))}
        </div>
      )}
    </div>
  )
}

function EfficacyCard({ estimate }: { estimate: EfficacyEstimate }) {
  const [expanded, setExpanded] = useState(false)
  const [challenging, setChallenging] = useState(false)

  return (
    <Card className="flex flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="font-semibold capitalize text-white">{estimate.intervention_type.replace(/_/g, ' ')}</p>
          <p className="text-sm text-white/50">{contextLabel(estimate)}</p>
        </div>
        <span className="whitespace-nowrap rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/70">
          {estimate.intervention_samples}× intervention · {estimate.control_samples}× control
        </span>
      </div>

      <p className="text-sm text-white/80">
        {estimate.recommendation ?? estimate.reason ?? 'Not enough comparable evidence yet.'}
      </p>

      <div className="flex gap-3 border-t border-white/10 pt-2 text-xs">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-white/50 underline decoration-dotted hover:text-white"
        >
          {expanded ? 'Hide details' : 'Inspect the numbers'}
        </button>
        <button
          type="button"
          onClick={() => setChallenging((v) => !v)}
          className="text-white/50 underline decoration-dotted hover:text-white"
        >
          Question this
        </button>
      </div>

      {expanded && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 border-t border-white/10 pt-2 text-xs text-white/60 sm:grid-cols-3">
          <div>
            <dt className="text-white/40">Status</dt>
            <dd>{estimate.status}</dd>
          </div>
          {estimate.effect !== null && (
            <div>
              <dt className="text-white/40">Effect</dt>
              <dd>{(estimate.effect * 100).toFixed(1)}%</dd>
            </div>
          )}
          {estimate.interval_low !== null && estimate.interval_high !== null && (
            <div>
              <dt className="text-white/40">95% interval</dt>
              <dd>
                {(estimate.interval_low * 100).toFixed(1)}% to {(estimate.interval_high * 100).toFixed(1)}%
              </dd>
            </div>
          )}
          {estimate.period_start && estimate.period_end && (
            <div className="col-span-2 sm:col-span-3">
              <dt className="text-white/40">Evidence period</dt>
              <dd>
                {new Date(estimate.period_start).toLocaleDateString()} –{' '}
                {new Date(estimate.period_end).toLocaleDateString()}
              </dd>
            </div>
          )}
          {estimate.valid_until && (
            <div className="col-span-2 sm:col-span-3">
              <dt className="text-white/40">Valid until</dt>
              <dd>{new Date(estimate.valid_until).toLocaleDateString()} without reinforcing evidence</dd>
            </div>
          )}
        </dl>
      )}

      {challenging && (
        <p className="border-t border-white/10 pt-2 text-xs text-white/50">
          This is computed from your recorded review history. If a specific review was graded wrong or does not
          belong, flag it from the History tab — corrected reviews stop counting as evidence here too.
        </p>
      )}
    </Card>
  )
}
