import { useEffect, useState } from 'react'
import { scenariosApi } from '../../lib/api'
import type { ScenarioVocabulary as Vocabulary, ScenarioWord } from '../../lib/types'
import { Card } from '../../components/ui/Card'

/**
 * Words worth having ready before a role-play (issue #144).
 *
 * Only words the learner already holds. Suggesting vocabulary they do not have
 * would be a shopping list dressed as preparation — this is "revise these
 * before you start", not "go and learn these first".
 *
 * A thin deck is said in words rather than shown as a two-item list. A very
 * short list reads as the feature being broken, when the true statement is
 * that there is not much here yet.
 */

function WordList({ words }: { words: ScenarioWord[] }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {words.map((word) => (
        <li
          key={word.id}
          className="rounded-full bg-white/10 px-3 py-1 text-sm text-white"
          title={word.translations.join(', ')}
        >
          {word.term}
          {word.cefr_level && <span className="ml-1 text-xs text-white/40">{word.cefr_level}</span>}
        </li>
      ))}
    </ul>
  )
}

export function ScenarioVocabulary({ scenarioKey }: { scenarioKey: string }) {
  const [vocabulary, setVocabulary] = useState<Vocabulary | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setVocabulary(null)
    setFailed(false)
    scenariosApi.vocabulary(scenarioKey).then(setVocabulary).catch(() => setFailed(true))
  }, [scenarioKey])

  if (failed) {
    return (
      <Card className="p-4">
        <p className="text-sm text-white/60">Could not load vocabulary for this scenario.</p>
      </Card>
    )
  }

  if (!vocabulary) return null

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="text-sm text-white/60">{vocabulary.detail}</p>

      {vocabulary.on_topic.length > 0 && (
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-white/40">You already know</p>
          <WordList words={vocabulary.on_topic} />
        </div>
      )}

      {vocabulary.related.length > 0 && (
        <div>
          {/* Named as related rather than folded in: these came through the
              knowledge graph, including words the learner confuses with an
              on-topic one — which is exactly what trips people up mid-
              conversation. */}
          <p className="mb-2 text-xs uppercase tracking-wide text-white/40">Related words</p>
          <WordList words={vocabulary.related} />
        </div>
      )}
    </Card>
  )
}
