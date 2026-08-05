import { useEffect, useState } from 'react'
import { groupsApi, practiceApi } from '../../lib/api'
import type { Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'

/**
 * Writing a sentence and having it corrected (issue #144).
 *
 * The endpoint already existed and was only reachable from inside a word's
 * practice flow — you had to be reviewing a specific word to use it. Here you
 * pick the word you want to practise, which is the order people actually think
 * in.
 *
 * The correction is shown *next to* the original, never replacing it. Swapping
 * in the corrected version hides what the learner wrote, which is the thing
 * they need to compare against.
 */
export function WritingPractice() {
  const [words, setWords] = useState<Word[]>([])
  const [wordId, setWordId] = useState<number | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ original: string; corrected: string; feedback: string } | null>(
    null,
  )
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

  async function correct() {
    if (!wordId || !text.trim()) return
    setBusy(true)
    setError(null)
    try {
      const response = await practiceApi.writingCorrection(wordId, text.trim())
      // The original is captured here rather than read back from the input,
      // which the learner may edit while reading the correction.
      setResult({
        original: text.trim(),
        corrected: response.corrected_text,
        feedback: response.feedback,
      })
    } catch {
      setError('Could not check that just now.')
    } finally {
      setBusy(false)
    }
  }

  if (words.length === 0) {
    return (
      <Card className="p-6">
        <p className="text-white/60">Add some words first — writing practice is built around one.</p>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col gap-3 p-6">
        <label className="text-sm text-white/70">
          Practise using
          <select
            value={wordId ?? ''}
            onChange={(event) => setWordId(Number(event.target.value))}
            aria-label="Word to practise"
            className="ml-2 rounded bg-white/10 p-2 text-white"
          >
            {words.map((word) => (
              <option key={word.id} value={word.id}>
                {word.term}
              </option>
            ))}
          </select>
        </label>

        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={4}
          placeholder="Write a sentence using it…"
          aria-label="Your sentence"
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-white"
        />

        <Button loading={busy} disabled={!text.trim() || !wordId} onClick={() => void correct()}>
          Check my writing
        </Button>

        {error && (
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
        )}
      </Card>

      {result && (
        <Card className="flex flex-col gap-3 p-6">
          <div>
            {/* Both versions, side by side. Replacing the original would hide
                the thing the learner needs to compare against. */}
            <p className="text-xs uppercase tracking-wide text-white/40">You wrote</p>
            <p className="text-white/70">{result.original}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-white/40">Corrected</p>
            <p className="text-white">{result.corrected}</p>
          </div>
          {result.feedback && <p className="text-sm text-white/60">{result.feedback}</p>}
        </Card>
      )}
    </div>
  )
}
