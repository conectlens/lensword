import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiRequestError, reviewApi } from '../../lib/api'
import { queueableRequest } from '../../lib/offlineQueue'
import type { ReviewOutcome, SessionSummary, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { FlashcardStack } from './FlashcardStack'

/**
 * Flip-and-swipe practice as a session (issue #338).
 *
 * A separate route rather than a sixth `mode`: `SessionMode` is a backend
 * enum describing *when* a session is taken (walking, night, a study
 * break), and flashcards are a way of answering that is orthogonal to all
 * of them. Adding a member would have meant the backend enumerating a
 * frontend interaction it has no opinion about. This starts an ordinary
 * `standard` session and draws it differently, so scheduling, streaks and
 * summaries are the same ones the existing mode produces — the whole point
 * of the issue's "no new scheduling logic client-side".
 */
export function FlashcardSessionPage() {
  const [searchParams] = useSearchParams()
  const groupId = searchParams.get('group')
  const navigate = useNavigate()

  const [status, setStatus] = useState<'loading' | 'empty' | 'reviewing' | 'summary'>('loading')
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [queue, setQueue] = useState<Word[]>([])
  const [index, setIndex] = useState(0)
  const [newWordsLearned, setNewWordsLearned] = useState(0)
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [busy, setBusy] = useState(false)

  const currentWord = queue[index]

  useEffect(() => {
    reviewApi
      .start('standard', groupId ? Number(groupId) : null, 20)
      .then((res) => {
        setSessionId(res.session_id)
        setQueue(res.words)
        setStatus(res.words.length ? 'reviewing' : 'empty')
      })
      .catch(() => setStatus('empty'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function answer(outcome: ReviewOutcome) {
    if (!sessionId || !currentWord || busy) return
    setBusy(true)
    const wasNew = currentWord.review_state.repetitions === 0
    try {
      // The same offline-tolerant path the existing review mode uses: an
      // append never conflicts, so this succeeds locally and syncs later.
      const result = await queueableRequest(
        () => reviewApi.answer(sessionId, currentWord.id, outcome),
        () => ({
          entity_type: 'review',
          entity_id: null,
          operation: 'append',
          payload: { session_id: sessionId, word_id: currentWord.id, outcome },
          base_revision: null,
        }),
      )
      if (result?.was_new_word_learned && wasNew) setNewWordsLearned((n) => n + 1)

      if (index + 1 < queue.length) setIndex((i) => i + 1)
      else await finish(sessionId)
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) setStatus('empty')
    } finally {
      setBusy(false)
    }
  }

  async function finish(id: number) {
    setSummary(await reviewApi.complete(id, newWordsLearned))
    setStatus('summary')
  }

  if (status === 'loading') return <Spinner />

  if (status === 'empty') {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <Icon name="task_alt" className="text-5xl text-primary" />
        <h1 className="font-display text-2xl font-bold text-white">Nothing due right now</h1>
        <p className="max-w-sm text-white/50">
          You&apos;re all caught up. Come back later, or add more words to review.
        </p>
        <Button onClick={() => navigate('/dashboard')}>Back to dashboard</Button>
      </div>
    )
  }

  if (status === 'summary' && summary) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-8 py-8 text-center">
        <Icon name="celebration" className="text-5xl text-primary" />
        <h1 className="font-display text-3xl font-bold text-white">Session complete!</h1>
        <Card className="grid w-full grid-cols-2 gap-6 p-6 sm:grid-cols-4">
          <Stat label="Duration" value={`${Math.round(summary.duration_seconds / 60)} min`} />
          <Stat label="Reviewed" value={summary.words_reviewed} />
          <Stat label="Correct" value={summary.correct_count} />
          <Stat label="New words" value={summary.new_words_learned} />
        </Card>
        <Button onClick={() => navigate('/dashboard')}>Back to dashboard</Button>
      </div>
    )
  }

  if (!currentWord) return <Spinner />

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-xl flex-col items-center justify-center gap-6">
      <div className="flex w-full items-center justify-between">
        <button
          aria-label="Close flashcard session"
          onClick={() => navigate('/dashboard')}
          className="flex h-10 w-10 items-center justify-center rounded-full hover:bg-white/10"
        >
          <Icon name="close" />
        </button>
        <span className="w-10" />
      </div>

      <FlashcardStack
        key={currentWord.id}
        word={currentWord}
        position={index + 1}
        total={queue.length}
        busy={busy}
        onAnswer={answer}
      />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="font-display text-2xl font-bold text-white">{value}</p>
      <p className="text-xs uppercase tracking-wide text-white/40">{label}</p>
    </div>
  )
}
