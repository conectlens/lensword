import { useEffect, useRef, useState } from 'react'
import { conversationsApi, groupsApi } from '../../lib/api'
import type { Conversation, ConversationMessage, Difficulty } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Select } from '../../components/ui/Select'

/**
 * Practising a conversation with corrections shown inline (issue #135).
 *
 * Two things this screen is careful about.
 *
 * **What you typed is never lost.** The server stores the learner's turn
 * before calling the model, so a model being unreachable leaves the message on
 * screen and the conversation resumable. This page mirrors that: on a failed
 * turn the learner's message is still appended, and the input is only cleared
 * once the message has been accepted.
 *
 * **Corrections are shown beside a turn, not instead of it.** Rewriting what
 * someone said into "the correct version" hides what they actually wrote,
 * which is the thing they need to see to learn from.
 */

const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  // Named rather than numeric — "gentle" is a choice someone can make, while
  // "difficulty 0.3" is one they would be guessing at.
  { value: 'gentle', label: 'Gentle' },
  { value: 'steady', label: 'Steady' },
  { value: 'stretch', label: 'Stretch me' },
]

function MessageBubble({ message }: { message: ConversationMessage }) {
  const fromLearner = message.speaker === 'learner'
  return (
    <div className={`flex ${fromLearner ? 'justify-end' : 'justify-start'}`}>
      <div className="max-w-[80%]">
        <div
          className={`rounded-2xl px-4 py-2 ${
            fromLearner ? 'bg-primary/20 text-white' : 'bg-white/10 text-white'
          }`}
        >
          {message.text}
        </div>

        {message.corrections.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1">
            {message.corrections.map((correction, index) => (
              <li
                key={`${correction.original}-${index}`}
                className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-100"
              >
                {/* The learner's own words are kept visible. Showing only the
                    corrected form hides what they actually wrote, which is the
                    thing they need to see. */}
                <s className="opacity-60">{correction.original}</s> → <b>{correction.corrected}</b>
                {correction.explanation && (
                  <span className="block text-xs opacity-80">{correction.explanation}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

export function ConversationPage() {
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [languages, setLanguages] = useState<string[]>([])
  const [language, setLanguage] = useState('')
  const [difficulty, setDifficulty] = useState<Difficulty>('steady')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    groupsApi.list().then((groups) => {
      const unique = [...new Set(groups.map((group) => group.target_language))]
      setLanguages(unique)
      if (unique[0]) setLanguage(unique[0])
    })
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conversation?.messages.length])

  async function start() {
    if (!language) return
    setBusy(true)
    setNotice(null)
    try {
      setConversation(await conversationsApi.start(language, difficulty))
    } catch {
      setNotice('Could not start a conversation.')
    } finally {
      setBusy(false)
    }
  }

  async function send() {
    if (!conversation || !draft.trim()) return
    setBusy(true)
    setNotice(null)
    const text = draft.trim()
    try {
      const result = await conversationsApi.send(conversation.id, text)
      // Appended regardless of status: the server stored it, so the screen
      // must show it. Clearing the box only after this keeps a failed send
      // from silently eating what someone typed.
      const added = [result.learner_message, result.tutor_message].filter(
        (message): message is ConversationMessage => message != null,
      )
      setConversation({ ...conversation, messages: [...conversation.messages, ...added] })
      setDraft('')
      if (result.status !== 'ok') {
        // The server's own wording, which distinguishes "not configured" from
        // "temporarily down".
        setNotice(result.detail ?? 'The tutor could not reply.')
      }
    } catch {
      setNotice('Could not send that message.')
    } finally {
      setBusy(false)
    }
  }

  if (!conversation) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <div>
          <h1 className="font-display text-3xl font-bold text-white">Conversation practice</h1>
          <p className="text-white/50">
            Talk in the language you are learning. Corrections appear beside what you wrote.
          </p>
        </div>

        <Card className="flex flex-wrap items-center gap-3 p-6">
          <label className="text-sm text-white/70">
            Language
            <Select
              size="sm"
              className="ml-2"
              aria-label="Conversation language"
              value={language}
              onValueChange={setLanguage}
              options={languages.map((value) => ({ value, label: value }))}
            />
          </label>

          <label className="text-sm text-white/70">
            Level
            <Select
              size="sm"
              className="ml-2"
              aria-label="Difficulty"
              value={difficulty}
              onValueChange={(next) => setDifficulty(next as Difficulty)}
              options={DIFFICULTIES.map((option) => ({ value: option.value, label: option.label }))}
            />
          </label>

          <Button loading={busy} disabled={!language} onClick={() => void start()}>
            Start talking
          </Button>
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
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-2xl font-bold text-white">
          {conversation.target_language}
        </h1>
        <Button size="sm" variant="ghost" onClick={() => setConversation(null)}>
          New conversation
        </Button>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto">
        {conversation.messages.length === 0 && (
          <p className="text-white/40">Say something to get started.</p>
        )}
        {conversation.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        <div ref={bottom} />
      </div>

      {notice && (
        <p role="alert" className="text-sm text-amber-200">
          {notice}
        </p>
      )}

      <div className="flex gap-3">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) void send()
          }}
          placeholder="Write something…"
          aria-label="Your message"
          maxLength={2000}
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 p-3 text-white"
        />
        <Button loading={busy} disabled={!draft.trim()} onClick={() => void send()}>
          Send
        </Button>
      </div>
    </div>
  )
}
