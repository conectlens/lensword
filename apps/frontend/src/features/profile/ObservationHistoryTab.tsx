import { useEffect, useState } from 'react'
import { observationsApi, ApiRequestError } from '../../lib/api'
import type { ObservationCorrectionReason, ObservationHistoryItem } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

/**
 * What LensWord has recorded about the learner's own reviews (issue #229
 * TODO 5), and a way to flag a row as misgraded or irrelevant without
 * deleting it — the flag is a new record, so the original observation is
 * still shown here even after it stops counting as diagnosis evidence.
 */

const PAGE_SIZE = 20

const OUTCOME_LABELS: Record<string, string> = {
  correct: 'Correct',
  incorrect: 'Incorrect',
  skipped: 'Skipped',
}

const REASON_LABELS: Record<ObservationCorrectionReason, string> = {
  misgraded: 'Misgraded',
  irrelevant: 'Irrelevant',
}

export function ObservationHistoryTab() {
  const [items, setItems] = useState<ObservationHistoryItem[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [loadingMore, setLoadingMore] = useState(false)
  const [flaggingId, setFlaggingId] = useState<string | null>(null)

  function load(offset: number) {
    return observationsApi.history(PAGE_SIZE, offset).then((page) => {
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]))
      setHasMore(page.has_more)
    })
  }

  useEffect(() => {
    load(0).then(() => setStatus('ready')).catch(() => setStatus('failed'))
  }, [])

  async function loadMore() {
    setLoadingMore(true)
    try {
      await load(items.length)
    } finally {
      setLoadingMore(false)
    }
  }

  async function submitCorrection(observationId: string, reason: ObservationCorrectionReason, note: string) {
    try {
      const correction = await observationsApi.correct(observationId, reason, note)
      setItems((prev) => prev.map((item) => (item.observation_id === observationId ? { ...item, correction } : item)))
      setFlaggingId(null)
    } catch (error) {
      // A 409 means someone flagged it in another tab already — the row
      // already shows a correction once we refresh it, so silently
      // reloading the page beats surfacing an error for something that
      // already happened the way the learner wanted.
      if (error instanceof ApiRequestError && error.status === 409) {
        await load(0)
      }
      setFlaggingId(null)
    }
  }

  if (status === 'loading') return <Spinner />

  if (status === 'failed') {
    return (
      <Card className="p-6">
        <p className="text-white/60">Could not load your review history just now.</p>
      </Card>
    )
  }

  if (items.length === 0) {
    return (
      <Card className="p-6">
        <p className="font-semibold text-white">Nothing recorded yet</p>
        <p className="mt-2 text-sm text-white/60">
          Review history shows up here once the acquisition diagnosis engine is on and you've answered a few questions.
        </p>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {items.map((item) => (
        <ObservationRow
          key={item.observation_id}
          item={item}
          isFlagging={flaggingId === item.observation_id}
          onStartFlag={() => setFlaggingId(item.observation_id)}
          onCancelFlag={() => setFlaggingId(null)}
          onSubmitFlag={(reason, note) => submitCorrection(item.observation_id, reason, note)}
        />
      ))}
      {hasMore && (
        <Button variant="secondary" onClick={loadMore} loading={loadingMore} className="self-center">
          Load more
        </Button>
      )}
    </div>
  )
}

function ObservationRow({
  item,
  isFlagging,
  onStartFlag,
  onCancelFlag,
  onSubmitFlag,
}: {
  item: ObservationHistoryItem
  isFlagging: boolean
  onStartFlag: () => void
  onCancelFlag: () => void
  onSubmitFlag: (reason: ObservationCorrectionReason, note: string) => void
}) {
  const [note, setNote] = useState('')

  return (
    <Card className="flex flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-white">{item.word_term ?? 'a deleted word'}</p>
          <p className="text-sm text-white/50">
            {OUTCOME_LABELS[item.outcome] ?? item.outcome}
            {item.modality && ` · ${item.modality}`}
            {' · '}
            {new Date(item.observed_at).toLocaleString()}
          </p>
        </div>
        {item.correction ? (
          <span className="whitespace-nowrap rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/70">
            Flagged: {REASON_LABELS[item.correction.reason]}
          </span>
        ) : (
          !isFlagging && (
            <Button variant="ghost" size="sm" onClick={onStartFlag}>
              Flag
            </Button>
          )
        )}
      </div>

      {isFlagging && (
        <div className="flex flex-col gap-2 border-t border-white/10 pt-3">
          <p className="text-sm text-white/60">Why should this not count as evidence?</p>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note"
            maxLength={500}
            className="h-10 w-full rounded-lg bg-white/5 px-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => onSubmitFlag('misgraded', note)}>
              Misgraded
            </Button>
            <Button size="sm" variant="secondary" onClick={() => onSubmitFlag('irrelevant', note)}>
              Irrelevant
            </Button>
            <Button size="sm" variant="ghost" onClick={onCancelFlag}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}
