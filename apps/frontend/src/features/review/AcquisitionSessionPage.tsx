import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { acquisitionApi, ApiRequestError } from '../../lib/api'
import type { AcquisitionState, ReviewOutcome, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

type Item = { state: AcquisitionState; word: Word }

export function AcquisitionSessionPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Item[]>([])
  const [index, setIndex] = useState(0)
  const [status, setStatus] = useState<'loading' | 'empty' | 'ready' | 'error'>('loading')
  const [feedback, setFeedback] = useState<ReviewOutcome | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    acquisitionApi.due().then(async (states) => {
      const loaded = await Promise.all(states.map(async (state) => ({ state, word: await acquisitionApi.word(state.word_id) })))
      setItems(loaded)
      setStatus(loaded.length ? 'ready' : 'empty')
    }).catch(() => setStatus('error'))
  }, [])

  const current = items[index]
  const progress = useMemo(() => items.length ? `${index + 1} / ${items.length}` : '', [index, items.length])

  async function answer(outcome: ReviewOutcome) {
    if (!current || submitting) return
    setSubmitting(true)
    setFeedback(outcome)
    try {
      await acquisitionApi.answer(current.word.id, outcome)
      window.setTimeout(() => {
        setFeedback(null)
        setSubmitting(false)
        if (index + 1 < items.length) setIndex((value) => value + 1)
        else setStatus('empty')
      }, 350)
    } catch (error) {
      setFeedback(null)
      setSubmitting(false)
      if (error instanceof ApiRequestError && error.status === 403) setStatus('error')
    }
  }

  if (status === 'loading') return <Spinner />
  if (status === 'error') return <EmptyState title="Stabilization unavailable" body="Turn on the acquisition loop in Settings, then try again." onBack={() => navigate('/dashboard')} />
  if (status === 'empty' || !current) return <EmptyState title="Nothing to stabilize" body="There are no graduated-recall prompts due right now." onBack={() => navigate('/dashboard')} />

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-2xl flex-col items-center justify-center gap-8">
      <div className="flex w-full items-center justify-between">
        <button aria-label="Close stabilization session" onClick={() => navigate('/dashboard')} className="flex h-10 w-10 items-center justify-center rounded-full hover:bg-white/10"><Icon name="close" /></button>
        <div className="text-center"><p className="text-sm font-bold text-white">{progress}</p><p className="text-xs text-white/40">Rung {current.state.rung + 1}</p></div>
        <span className="w-10" />
      </div>
      <div className="w-full text-center text-sm font-medium uppercase tracking-wide text-white/40">Stabilize this word</div>
      <Card className="flex w-full flex-col gap-8 p-6 text-center sm:p-10">
        <div><h1 className="font-display text-4xl font-bold text-white sm:text-5xl">{current.word.term}</h1><p className="mt-2 text-lg text-white/50">{current.word.target_language}</p></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Button size="lg" icon="check" onClick={() => answer('correct')} disabled={submitting}>I remembered it</Button>
          <Button size="lg" variant="secondary" icon="close" onClick={() => answer('incorrect')} disabled={submitting}>I need another pass</Button>
        </div>
        {feedback && <p className={feedback === 'correct' ? 'font-medium text-success' : 'font-medium text-danger'}>{feedback === 'correct' ? 'Correct' : 'Keep going'}</p>}
      </Card>
    </div>
  )
}

function EmptyState({ title, body, onBack }: { title: string; body: string; onBack: () => void }) {
  return <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center"><Icon name="task_alt" className="text-5xl text-primary" /><h1 className="font-display text-2xl font-bold text-white">{title}</h1><p className="max-w-sm text-white/50">{body}</p><Button onClick={onBack}>Back to dashboard</Button></div>
}
