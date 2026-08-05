import { useEffect, useState } from 'react'
import { wordsApi } from '../../lib/api'
import type { AiState, WordRevision } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'

/**
 * Whether a model wrote this card, whether anyone has checked it, and what it
 * said before (issue #140).
 *
 * The badge is the point, and it only means anything if it can be wrong-footed:
 * "verified" has to stop being true when a model rewrites the text, or it
 * degrades into decoration. The backend clears it on re-enrichment; this shows
 * the current state rather than caching a guess.
 *
 * A card nobody claimed a model wrote shows no badge at all. "Unverified" on
 * something a person typed would invite them to verify their own writing,
 * which means nothing.
 */

const BADGE: Record<AiState, { label: string; className: string } | null> = {
  human: null,
  unverified: { label: 'AI-generated · unchecked', className: 'bg-amber-400/15 text-amber-200' },
  verified: { label: 'AI-generated · verified', className: 'bg-emerald-400/15 text-emerald-200' },
}

const FIELD_LABELS: Record<string, string> = {
  translations: 'Translations',
  definition: 'Definition',
  example_sentence: 'Example',
  mnemonic: 'Mnemonic',
  part_of_speech: 'Part of speech',
  cefr_level: 'CEFR level',
  pronunciation: 'Pronunciation',
  collocations: 'Collocations',
  synonyms: 'Synonyms',
  antonyms: 'Antonyms',
  topics: 'Topics',
}

const SOURCE_LABELS: Record<WordRevision['source'], string> = {
  ai: 'by the model',
  human: 'by you',
  // Named distinctly on purpose: "I set the level on forty cards" is a
  // different degree of attention from "I changed this card".
  bulk: 'by you, in a bulk edit',
}

export function AiStateBadge({ state }: { state: AiState }) {
  const badge = BADGE[state]
  if (!badge) return null
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badge.className}`}>
      {badge.label}
    </span>
  )
}

type Props = {
  wordId: number
  state: AiState
  onStateChange: (state: AiState) => void
}

export function AiProvenancePanel({ wordId, state, onStateChange }: Props) {
  const [history, setHistory] = useState<WordRevision[] | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (showHistory && history === null) {
      wordsApi.history(wordId).then(setHistory).catch(() => setHistory([]))
    }
  }, [showHistory, history, wordId])

  async function toggleVerified() {
    setBusy(true)
    try {
      const next = state === 'verified' ? await wordsApi.unverify(wordId) : await wordsApi.verify(wordId)
      onStateChange(next.state)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <AiStateBadge state={state} />
        {state !== 'human' && (
          <Button size="sm" variant="secondary" loading={busy} onClick={() => void toggleVerified()}>
            {state === 'verified' ? 'Withdraw verification' : 'Mark as verified'}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setShowHistory((open) => !open)}>
          {showHistory ? 'Hide history' : 'Show history'}
        </Button>
      </div>

      {showHistory && (
        <Card className="p-4">
          {history === null && <p className="text-sm text-white/50">Loading…</p>}
          {history?.length === 0 && (
            <p className="text-sm text-white/50">
              Nothing has changed on this card since it was created.
            </p>
          )}
          {history && history.length > 0 && (
            <ul className="flex flex-col gap-3">
              {history.map((entry, index) => (
                <li key={`${entry.field}-${entry.changed_at}-${index}`} className="text-sm">
                  <p className="font-semibold text-white">
                    {FIELD_LABELS[entry.field] ?? entry.field}{' '}
                    <span className="font-normal text-white/40">
                      changed {SOURCE_LABELS[entry.source]}
                    </span>
                  </p>
                  {/* "Added" and "replaced" are different facts, so an absent
                      previous value is said rather than rendered as a blank. */}
                  <p className="text-white/60">
                    {entry.before_value === null ? (
                      <em>added</em>
                    ) : (
                      <s className="text-white/40">{entry.before_value}</s>
                    )}{' '}
                    → {entry.after_value ?? <em>removed</em>}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
