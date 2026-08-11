import { useEffect, useRef, useState } from 'react'
import { companionApi, groupsApi, settingsApi } from '../../lib/api'
import type { CompanionSession, CompanionTurn } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Select } from '../../components/ui/Select'
import { Spinner } from '../../components/ui/Spinner'
import { Textarea } from '../../components/ui/Textarea'

/**
 * The in-app chat assistant (issue #343).
 *
 * Three things this screen is careful about.
 *
 * **It is the same session an external companion drives.** Every exchange is
 * written as ordinary companion turns through `/api/v1/companion/sessions`,
 * so a conversation started here stays readable, exportable and resumable
 * through every other companion surface instead of living in a parallel
 * store only this page understands.
 *
 * **A feature that is switched off is hidden, not broken.** The backend
 * gates every companion route on `ai_companion_enabled`. Reading the flag
 * first turns "every request 403s" into "the surface isn't offered", which
 * is the difference between an install that looks broken and one that
 * looks configured.
 *
 * **What you typed is never lost.** The server stores the user's turn before
 * calling the model, so an unreachable provider costs the answer and not the
 * message. This page mirrors that: the turn is appended whatever the status,
 * and the composer is cleared only once the server has accepted it.
 */

function TurnBubble({ turn }: { turn: CompanionTurn }) {
  const fromUser = turn.role === 'user'
  return (
    <div className={`flex ${fromUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 whitespace-pre-wrap ${
          fromUser ? 'bg-primary/20 text-white' : 'bg-white/10 text-white'
        }`}
      >
        {turn.content}
      </div>
    </div>
  )
}

export function CompanionChatPage() {
  // null while unknown — the surface must not flash into view before the
  // flag that gates it has been read.
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [session, setSession] = useState<CompanionSession | null>(null)
  const [turns, setTurns] = useState<CompanionTurn[]>([])
  const [languages, setLanguages] = useState<string[]>([])
  const [language, setLanguage] = useState('')
  const [goal, setGoal] = useState('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  // Kept across a failed send so pressing Send again is the *same* request
  // rather than a second one: the backend returns the stored exchange
  // instead of asking the model the same thing twice.
  const pendingOperationId = useRef<string | null>(null)

  useEffect(() => {
    settingsApi
      .getRecallSettings()
      .then((settings) => setEnabled(settings.ai_companion_enabled))
      .catch(() => setEnabled(false))
  }, [])

  useEffect(() => {
    if (!enabled) return
    groupsApi
      .list()
      .then((groups) => {
        const unique = [...new Set(groups.map((group) => group.target_language))]
        setLanguages(unique)
        if (unique[0]) setLanguage(unique[0])
      })
      .catch(() => setLanguages([]))
  }, [enabled])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length])

  async function start() {
    setBusy(true)
    setNotice(null)
    try {
      const started = await companionApi.start(goal.trim() || null, language || null)
      setSession(started)
      setTurns(started.turns ?? [])
    } catch {
      setNotice('Could not start a chat session.')
    } finally {
      setBusy(false)
    }
  }

  async function send() {
    if (!session || !draft.trim()) return
    const content = draft.trim()
    const operationId = pendingOperationId.current ?? crypto.randomUUID()
    pendingOperationId.current = operationId

    setBusy(true)
    setNotice(null)
    try {
      const result = await companionApi.chat(session.id, content, operationId)
      // Appended regardless of status: the server stored the user's turn, so
      // the screen has to show it. Clearing the composer only after this is
      // what stops a failed send from eating the message.
      const added = [result.user_turn, result.assistant_turn].filter(
        (turn): turn is CompanionTurn => turn != null,
      )
      setTurns((current) => [...current, ...added])
      setDraft('')

      if (result.status === 'ok') {
        pendingOperationId.current = null
      } else {
        // The server's own wording, which distinguishes "not configured"
        // from "temporarily down". The operation id is kept so the retry
        // reuses the turn already stored.
        setNotice(result.detail ?? 'The assistant could not reply.')
      }
    } catch {
      setNotice('Could not send that message.')
    } finally {
      setBusy(false)
    }
  }

  async function finish() {
    if (!session) return
    setBusy(true)
    try {
      await companionApi.finish(session.id)
      setSession(null)
      setTurns([])
      pendingOperationId.current = null
    } catch {
      setNotice('Could not end the chat.')
    } finally {
      setBusy(false)
    }
  }

  if (enabled === null) {
    return (
      <div className="flex justify-center p-12">
        <Spinner />
      </div>
    )
  }

  // Hidden rather than erroring: this matches the backend's own gate, and an
  // install with the companion switched off is a healthy install.
  if (!enabled) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <h1 className="font-display text-3xl font-bold text-white">Assistant</h1>
        <Card className="p-6">
          <p className="text-white/60">
            The AI companion is switched off for this account. Turn it on in Settings to chat here.
          </p>
        </Card>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <div>
          <h1 className="font-display text-3xl font-bold text-white">Assistant</h1>
          <p className="text-white/50">
            Ask about anything you are learning. The conversation is saved to your account and can be
            picked up from any connected companion.
          </p>
        </div>

        <Card className="flex flex-col gap-4 p-6">
          <label className="text-sm text-white/70">
            Language
            <Select
              size="sm"
              className="ml-2"
              aria-label="Chat language"
              value={language}
              onValueChange={setLanguage}
              options={languages.map((value) => ({ value, label: value }))}
            />
          </label>

          <Textarea
            name="companion-goal"
            label="What do you want help with? (optional)"
            rows={2}
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
          />

          <div>
            <Button loading={busy} onClick={() => void start()}>
              Start chatting
            </Button>
          </div>
        </Card>

        {notice && (
          <p role="alert" className="text-sm text-red-300">
            {notice}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-3xl font-bold text-white">Assistant</h1>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => void finish()}>
          End chat
        </Button>
      </div>

      <Card className="flex flex-col gap-3 p-6">
        {turns.length === 0 && (
          <p className="text-white/40">Say something to get started.</p>
        )}
        {turns.map((turn) => (
          <TurnBubble key={turn.id} turn={turn} />
        ))}
        {busy && (
          <div className="flex justify-start" aria-live="polite">
            <span className="flex items-center gap-2 rounded-2xl bg-white/10 px-4 py-2 text-white/60">
              <Icon name="progress_activity" className="animate-spin" /> Thinking…
            </span>
          </div>
        )}
        <div ref={bottom} />
      </Card>

      {notice && (
        <p role="alert" className="text-sm text-red-300">
          {notice}
        </p>
      )}

      <div className="flex flex-col gap-2">
        <Textarea
          name="companion-message"
          aria-label="Message"
          rows={3}
          value={draft}
          placeholder="Type a message…"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter is a newline — the convention every
            // other chat surface these users touch already follows.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void send()
            }
          }}
        />
        <div className="flex justify-end">
          <Button loading={busy} disabled={!draft.trim()} onClick={() => void send()}>
            Send
          </Button>
        </div>
      </div>
    </div>
  )
}
