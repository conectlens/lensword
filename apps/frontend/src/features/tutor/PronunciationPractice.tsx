import { useEffect, useState } from 'react'
import { groupsApi, practiceApi } from '../../lib/api'
import type { Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Select } from '../../components/ui/Select'

/**
 * Checking a pronunciation attempt (issue #144).
 *
 * The endpoint takes a *transcript*, not audio — it judges what was heard, not
 * how it sounded. That distinction is stated on screen rather than left for
 * the learner to infer from a wrong-looking result: told "your pronunciation
 * was accepted" after typing the word, they would reasonably conclude the
 * feature is fake. Told it is checking the transcript, it is a spelling-from-
 * speech check, which is a real thing to practise.
 */
export function PronunciationPractice() {
  const [words, setWords] = useState<Word[]>([])
  const [wordId, setWordId] = useState<number | null>(null)
  const [transcript, setTranscript] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ accepted: boolean; feedback: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    groupsApi.list().then(async (groups) => {
      const first = groups[0]
      if (!first) return
      const all = await groupsApi.words(first.id)
      setWords(all)
      if (all[0]) setWordId(all[0].id)
    })
  }, [])

  async function check() {
    if (!wordId || !transcript.trim()) return
    setBusy(true)
    setError(null)
    try {
      setResult(await practiceApi.pronunciationFeedback(wordId, transcript.trim()))
    } catch {
      setError('Could not check that just now.')
    } finally {
      setBusy(false)
    }
  }

  if (words.length === 0) {
    return (
      <Card className="p-6">
        <p className="text-white/60">Add some words first — this checks one word at a time.</p>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col gap-3 p-6">
        {/* Said plainly. A learner told "accepted" after typing the word would
            reasonably conclude the feature is fake. */}
        <p className="text-sm text-white/50">
          Say the word aloud, then type what you hear yourself say. This checks the transcript,
          not the sound.
        </p>

        <label className="text-sm text-white/70">
          Word
          <Select
            size="sm"
            className="ml-2"
            aria-label="Word to pronounce"
            value={wordId ? String(wordId) : undefined}
            onValueChange={(next) => {
              setWordId(Number(next))
              setResult(null)
            }}
            options={words.map((word) => ({ value: String(word.id), label: word.term }))}
          />
        </label>

        <input
          value={transcript}
          onChange={(event) => setTranscript(event.target.value)}
          placeholder="What you said…"
          aria-label="Your transcript"
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-white"
        />

        <Button loading={busy} disabled={!transcript.trim() || !wordId} onClick={() => void check()}>
          Check
        </Button>

        {error && (
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
        )}
      </Card>

      {result && (
        <Card className="p-6">
          <p
            role="status"
            className={`font-semibold ${result.accepted ? 'text-emerald-300' : 'text-amber-200'}`}
          >
            {result.accepted ? 'Close enough' : 'Not quite'}
          </p>
          {result.feedback && <p className="mt-2 text-sm text-white/60">{result.feedback}</p>}
        </Card>
      )}
    </div>
  )
}
