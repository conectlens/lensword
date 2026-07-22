import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiRequestError, reviewApi } from '../../lib/api'
import type { SessionMode, SessionSummary, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

const MULTIPLE_CHOICE_MODES: SessionMode[] = ['walking', 'night', 'break']

const MODE_COPY: Record<SessionMode, { title: string; subtitle: string }> = {
  standard: { title: 'Review session', subtitle: 'Type the translation you remember.' },
  focus: { title: 'Focus session', subtitle: 'A quick recall between focus blocks.' },
  walking: { title: 'Walking mode', subtitle: 'Answer quickly and keep walking.' },
  night: { title: 'Night review', subtitle: 'A few gentle questions before sleep.' },
  break: { title: 'Study break recall', subtitle: "Let's lock in a couple of words before your break." },
}

function shuffle<T>(arr: T[]): T[] {
  const copy = [...arr]
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[copy[i], copy[j]] = [copy[j], copy[i]]
  }
  return copy
}

export function ReviewSessionPage() {
  const [searchParams] = useSearchParams()
  const mode = (searchParams.get('mode') as SessionMode) || 'standard'
  const groupId = searchParams.get('group')
  const navigate = useNavigate()

  const [status, setStatus] = useState<'loading' | 'empty' | 'reviewing' | 'summary'>('loading')
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [queue, setQueue] = useState<Word[]>([])
  const [index, setIndex] = useState(0)
  const [typedAnswer, setTypedAnswer] = useState('')
  const [feedback, setFeedback] = useState<'correct' | 'incorrect' | null>(null)
  const [newWordsLearned, setNewWordsLearned] = useState(0)
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [secondsLeft, setSecondsLeft] = useState(25 * 60)

  const isMultipleChoice = MULTIPLE_CHOICE_MODES.includes(mode)
  const currentWord = queue[index]

  useEffect(() => {
    reviewApi
      .start(mode, groupId ? Number(groupId) : null, mode === 'night' ? 3 : mode === 'break' ? 2 : 20)
      .then((res) => {
        setSessionId(res.session_id)
        setQueue(res.words)
        setStatus('reviewing')
      })
      .catch((err) => {
        if (err instanceof ApiRequestError && err.status === 409) setStatus('empty')
        else setStatus('empty')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (mode !== 'focus' || status !== 'reviewing') return
    const timer = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(timer)
  }, [mode, status])

  const choices = useMemo(() => {
    if (!isMultipleChoice || !currentWord) return []
    const correct = currentWord.translations[0] ?? currentWord.term
    const distractorPool = queue
      .filter((w) => w.id !== currentWord.id)
      .map((w) => w.translations[0])
      .filter((t): t is string => Boolean(t))
    const distractors = shuffle(distractorPool).slice(0, 2)
    while (distractors.length < 2) distractors.push('None of the above')
    return shuffle([correct, ...distractors])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentWord?.id])

  async function submitOutcome(outcome: 'correct' | 'incorrect' | 'skipped') {
    if (!sessionId || !currentWord) return
    setFeedback(outcome === 'skipped' ? null : outcome)
    const wasNew = currentWord.review_state.repetitions === 0
    const result = await reviewApi.answer(sessionId, currentWord.id, outcome)
    if (result.was_new_word_learned && wasNew) setNewWordsLearned((n) => n + 1)

    setTimeout(
      () => {
        setFeedback(null)
        setTypedAnswer('')
        if (index + 1 < queue.length) {
          setIndex((i) => i + 1)
        } else {
          finishSession()
        }
      },
      outcome === 'skipped' ? 0 : 500,
    )
  }

  async function finishSession() {
    if (!sessionId) return
    const result = await reviewApi.complete(sessionId, newWordsLearned)
    setSummary(result)
    setStatus('summary')
  }

  function handleTypedSubmit() {
    if (!currentWord) return
    const normalized = typedAnswer.trim().toLowerCase()
    const isCorrect = currentWord.translations.some((t) => t.toLowerCase() === normalized)
    submitOutcome(isCorrect ? 'correct' : 'incorrect')
  }

  if (status === 'loading') return <Spinner />

  if (status === 'empty') {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <Icon name="task_alt" className="text-5xl text-primary" />
        <h1 className="font-display text-2xl font-bold text-white">Nothing due right now</h1>
        <p className="max-w-sm text-white/50">You&apos;re all caught up. Come back later, or add more words to review.</p>
        <Button onClick={() => navigate('/dashboard')}>Back to dashboard</Button>
      </div>
    )
  }

  if (status === 'summary' && summary) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-8 py-8 text-center">
        <Icon name="celebration" className="text-5xl text-primary" />
        <div>
          <h1 className="font-display text-3xl font-bold text-white">Session complete!</h1>
          <p className="text-white/50">Great work! Here&apos;s how you did.</p>
        </div>
        <Card className="grid w-full grid-cols-2 gap-6 p-6 sm:grid-cols-4">
          <Stat label="Duration" value={`${Math.round(summary.duration_seconds / 60)} min`} />
          <Stat label="Reviewed" value={summary.words_reviewed} />
          <Stat label="Correct" value={summary.correct_count} />
          <Stat label="New words" value={summary.new_words_learned} />
        </Card>
        <div className="w-full">
          <p className="mb-2 text-sm text-white/50">Accuracy</p>
          <div className="h-3 w-full rounded-full bg-white/10">
            <div className="h-3 rounded-full bg-primary" style={{ width: `${summary.accuracy_percent}%` }} />
          </div>
          <p className="mt-1 text-right text-sm font-medium text-white">{summary.accuracy_percent}%</p>
        </div>
        <Button size="lg" className="w-full" onClick={() => navigate('/dashboard')}>
          Go to dashboard
        </Button>
      </div>
    )
  }

  if (!currentWord) return <Spinner />

  const copy = MODE_COPY[mode]

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-2xl flex-col items-center justify-center gap-8">
      <div className="flex w-full items-center justify-between">
        <button onClick={() => navigate('/dashboard')} className="flex h-10 w-10 items-center justify-center rounded-full hover:bg-white/10">
          <Icon name="close" />
        </button>
        <div className="flex flex-col items-center gap-1">
          <p className="text-sm font-bold text-white">{index + 1} / {queue.length}</p>
          <div className="h-1.5 w-40 rounded-full bg-white/10">
            <div className="h-1.5 rounded-full bg-primary" style={{ width: `${((index + 1) / queue.length) * 100}%` }} />
          </div>
        </div>
        <div className="w-10 text-right text-sm text-white/40">
          {mode === 'focus' && `${String(Math.floor(secondsLeft / 60)).padStart(2, '0')}:${String(secondsLeft % 60).padStart(2, '0')}`}
          {mode === 'walking' && `${(index + 1) * 175} steps`}
        </div>
      </div>

      <div className="w-full text-center text-sm font-medium uppercase tracking-wide text-white/40">{copy.title} · {copy.subtitle}</div>

      <Card className="flex w-full flex-col gap-8 p-6 sm:p-10">
        <div className="text-center">
          <h1 className="font-display text-4xl font-bold text-white sm:text-5xl">{currentWord.term}</h1>
          <p className="mt-2 text-lg text-white/50">{currentWord.target_language}</p>
        </div>

        {isMultipleChoice ? (
          <div className="flex flex-col gap-3">
            {choices.map((choice) => (
              <button
                key={choice}
                onClick={() => submitOutcome(choice === (currentWord.translations[0] ?? currentWord.term) ? 'correct' : 'incorrect')}
                disabled={feedback !== null}
                className="rounded-lg border border-white/10 bg-white/5 p-4 text-left text-white transition-colors hover:border-primary hover:bg-primary/10 disabled:opacity-60"
              >
                {choice}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-2">
              <span className="text-sm font-medium text-white/70">Type the translation</span>
              <input
                autoFocus
                value={typedAnswer}
                onChange={(e) => setTypedAnswer(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleTypedSubmit()}
                placeholder="Your answer..."
                className="h-14 w-full rounded-lg border-none bg-canvas-dark px-4 text-base text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </label>
            <Button size="lg" onClick={handleTypedSubmit} disabled={!typedAnswer.trim()}>
              Check
            </Button>
          </div>
        )}

        {feedback && (
          <p className={`text-center font-medium ${feedback === 'correct' ? 'text-success' : 'text-danger'}`}>
            {feedback === 'correct' ? 'Correct!' : `Not quite — "${currentWord.translations[0] ?? ''}"`}
          </p>
        )}
      </Card>

      <button onClick={() => submitOutcome('skipped')} className="text-white/40 hover:text-white/70">
        {mode === 'night' ? 'Skip night session' : "I don't know"}
      </button>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-xs text-white/50">{label}</p>
    </div>
  )
}
