import { useState } from 'react'
import { ConversationPage } from './ConversationPage'
import { ScenarioPage } from './ScenarioPage'
import { WritingPractice } from './WritingPractice'
import { PronunciationPractice } from './PronunciationPractice'

/**
 * One page for speaking and writing practice (issue #144).
 *
 * The four modes already existed and were scattered: free conversation and
 * role-play on their own routes, writing correction and pronunciation feedback
 * reachable only from inside a word's practice flow. Someone who wanted to
 * "practise" had to know which of four places to go, which is a navigation
 * problem masquerading as four features.
 *
 * They are composed rather than rewritten. Each mode keeps its own component
 * and its own endpoints; this page only decides which is on screen. Merging
 * their internals would have produced one large component that is harder to
 * change than the four it replaced.
 */

const MODES = [
  { key: 'conversation', label: 'Conversation' },
  { key: 'roleplay', label: 'Role-play' },
  { key: 'writing', label: 'Writing' },
  { key: 'pronunciation', label: 'Pronunciation' },
] as const

type Mode = (typeof MODES)[number]['key']

export function PracticeLabPage() {
  const [mode, setMode] = useState<Mode>('conversation')

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div>
        <h1 className="font-display text-3xl font-bold text-white">Practice Lab</h1>
        <p className="text-white/50">Speak, write, and practise real situations in one place.</p>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-white/10">
        {MODES.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => setMode(option.key)}
            aria-current={mode === option.key ? 'page' : undefined}
            className={`px-4 py-2 text-sm font-semibold transition ${
              mode === option.key
                ? 'border-b-2 border-primary text-white'
                : 'text-white/50 hover:text-white/80'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* Mounted one at a time rather than hidden with CSS: a conversation
          left mounted behind another tab would keep its state and its in-flight
          requests, and coming back to a half-finished turn from an hour ago is
          worse than starting cleanly. */}
      {mode === 'conversation' && <ConversationPage />}
      {mode === 'roleplay' && <ScenarioPage />}
      {mode === 'writing' && <WritingPractice />}
      {mode === 'pronunciation' && <PronunciationPractice />}
    </div>
  )
}
