import { useEffect, useRef, useState } from 'react'
import { conversationsApi, groupsApi, scenariosApi } from '../../lib/api'
import type {
  ConversationMessage,
  Scenario,
  ScenarioAttempt,
} from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

/**
 * Role-play with a scored summary at the end (issue #136).
 *
 * The scoring screen is where this goes wrong most easily. An attempt too
 * short to judge is told so rather than given a number: a confident 72/100
 * derived from three messages is exactly the kind of figure a learner believes
 * because it looks precise, and once they act on it the feature has done harm
 * rather than nothing.
 *
 * Goals stay on screen during the conversation. A role-play whose tasks you
 * have to remember is a memory test wearing a conversation's clothes.
 */

const DIMENSION_LABELS: Record<string, string> = {
  vocabulary: 'Vocabulary',
  grammar: 'Grammar',
  fluency: 'Fluency',
  task_completion: 'Task completion',
}

function Evaluation({ attempt }: { attempt: ScenarioAttempt }) {
  const evaluation = attempt.evaluation
  if (!evaluation) return null

  if (!evaluation.scored) {
    return (
      <Card className="p-6">
        <p className="font-semibold text-white">Not scored</p>
        {/* The reason, not a zero. */}
        <p className="mt-2 text-sm text-white/60">{evaluation.detail}</p>
      </Card>
    )
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-baseline justify-between">
        <h2 className="font-display text-xl font-bold text-white">How it went</h2>
        {evaluation.overall !== null && (
          <span className="text-2xl font-black text-primary">{evaluation.overall}</span>
        )}
      </div>

      {evaluation.summary && <p className="text-sm text-white/70">{evaluation.summary}</p>}

      <div className="flex flex-col gap-2">
        {evaluation.scores.map((score) => (
          <div key={score.dimension}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-white">
                {DIMENSION_LABELS[score.dimension] ?? score.dimension}
              </span>
              <span className="text-white/60">{score.score}</span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-primary" style={{ width: `${score.score}%` }} />
            </div>
            {score.comment && <p className="mt-1 text-xs text-white/50">{score.comment}</p>}
          </div>
        ))}
      </div>

      <div>
        <p className="mb-1 text-sm font-semibold text-white">Tasks</p>
        <ul className="flex flex-col gap-1 text-sm">
          {attempt.scenario.goals.map((goal) => {
            const met = evaluation.goals_met.includes(goal)
            return (
              <li key={goal} className={met ? 'text-emerald-300' : 'text-white/50'}>
                {met ? '✓' : '○'} {goal}
              </li>
            )
          })}
        </ul>
      </div>
    </Card>
  )
}

export function ScenarioPage() {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null)
  const [languages, setLanguages] = useState<string[]>([])
  const [language, setLanguage] = useState('')
  const [attempt, setAttempt] = useState<ScenarioAttempt | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scenariosApi.list().then(setScenarios).catch(() => setScenarios([]))
    groupsApi.list().then((groups) => {
      const unique = [...new Set(groups.map((group) => group.target_language))]
      setLanguages(unique)
      if (unique[0]) setLanguage(unique[0])
    })
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  async function begin(scenario: Scenario) {
    if (!language) return
    setBusy(true)
    setNotice(null)
    try {
      setAttempt(await scenariosApi.start(scenario.key, language))
      setMessages([])
    } catch {
      setNotice('Could not start that scenario.')
    } finally {
      setBusy(false)
    }
  }

  async function send() {
    if (!attempt || !draft.trim()) return
    setBusy(true)
    setNotice(null)
    try {
      const result = await conversationsApi.send(attempt.session_id, draft.trim())
      // Appended regardless of status — the server stored the learner's turn
      // before calling the model, and the screen must not contradict that.
      setMessages((current) => [
        ...current,
        ...[result.learner_message, result.tutor_message].filter(
          (message): message is ConversationMessage => message != null,
        ),
      ])
      setDraft('')
      if (result.status !== 'ok') setNotice(result.detail ?? 'The tutor could not reply.')
    } catch {
      setNotice('Could not send that message.')
    } finally {
      setBusy(false)
    }
  }

  async function finish() {
    if (!attempt) return
    setBusy(true)
    try {
      setAttempt(await scenariosApi.finish(attempt.id))
    } catch {
      setNotice('Could not finish that attempt.')
    } finally {
      setBusy(false)
    }
  }

  if (!scenarios) return <Spinner />

  if (!attempt) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <div>
          <h1 className="font-display text-3xl font-bold text-white">Role-play</h1>
          <p className="text-white/50">
            Practise a real situation, then see how it went.
          </p>
        </div>

        <label className="text-sm text-white/70">
          Language
          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            aria-label="Role-play language"
            className="ml-2 rounded bg-white/10 p-2 text-white"
          >
            {languages.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          {scenarios.map((scenario) => (
            <Card key={scenario.key} className="flex flex-col gap-3 p-5">
              <h2 className="font-semibold text-white">{scenario.title}</h2>
              <p className="text-sm text-white/60">{scenario.briefing}</p>
              <ul className="text-xs text-white/40">
                {scenario.goals.map((goal) => (
                  <li key={goal}>• {goal}</li>
                ))}
              </ul>
              <Button size="sm" loading={busy} disabled={!language} onClick={() => void begin(scenario)}>
                Start
              </Button>
            </Card>
          ))}
        </div>

        {notice && (
          <p role="alert" className="text-sm text-red-300">
            {notice}
          </p>
        )}
      </div>
    )
  }

  const finished = attempt.finished_at !== null

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-2xl font-bold text-white">{attempt.scenario.title}</h1>
        <Button size="sm" variant="ghost" onClick={() => setAttempt(null)}>
          Pick another
        </Button>
      </div>

      {/* Kept on screen throughout: a role-play whose tasks you have to
          remember is a memory test wearing a conversation's clothes. */}
      <Card className="p-4">
        <p className="text-sm text-white/60">{attempt.scenario.briefing}</p>
        <ul className="mt-2 text-xs text-white/40">
          {attempt.scenario.goals.map((goal) => (
            <li key={goal}>• {goal}</li>
          ))}
        </ul>
      </Card>

      <div className="flex flex-col gap-3">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.speaker === 'learner' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2 ${
                message.speaker === 'learner' ? 'bg-primary/20 text-white' : 'bg-white/10 text-white'
              }`}
            >
              {message.text}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      {notice && (
        <p role="alert" className="text-sm text-amber-200">
          {notice}
        </p>
      )}

      {finished ? (
        <Evaluation attempt={attempt} />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex gap-3">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) void send()
              }}
              placeholder="Say something…"
              aria-label="Your message"
              maxLength={2000}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 p-3 text-white"
            />
            <Button loading={busy} disabled={!draft.trim()} onClick={() => void send()}>
              Send
            </Button>
          </div>
          <Button variant="secondary" loading={busy} onClick={() => void finish()}>
            Finish and score
          </Button>
        </div>
      )}
    </div>
  )
}
