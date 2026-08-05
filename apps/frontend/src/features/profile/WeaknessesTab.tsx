import { useEffect, useState } from 'react'
import { settingsApi } from '../../lib/api'
import type { WeaknessProfile } from '../../lib/types'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

/**
 * What the learner keeps getting wrong (issue #134).
 *
 * The hardest part of this screen is what it says when it knows nothing. An
 * empty list reads as "you have no weaknesses", which is a claim, and a wrong
 * one — so a profile without enough evidence says so in words.
 *
 * Counts are shown next to every percentage for the same reason: 60% of five
 * mistakes and 60% of five hundred are different claims, and a bare percentage
 * lets the reader mistake one for the other.
 */

// Categories are stored as machine strings so they survive a schema change.
// Displayed names live here rather than in the API, because how a weakness is
// phrased to a learner is a UI decision — "not recalled" is a fact, "you
// haven't learned this yet" is a judgement about them.
const CATEGORY_LABELS: Record<string, string> = {
  wrong_word: 'Answered with a different word',
  spelling: 'Spelling',
  inflection: 'Word form (tense, case, agreement)',
  sense: 'Right word, wrong sense',
  not_recalled: 'Not recalled',
  unknown: 'Uncategorised',
}

function label(category: string): string {
  return CATEGORY_LABELS[category] ?? 'Uncategorised'
}

export function WeaknessesTab() {
  const [profile, setProfile] = useState<WeaknessProfile | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    settingsApi.weaknesses().then(setProfile).catch(() => setFailed(true))
  }, [])

  if (failed) {
    return (
      <Card className="p-6">
        <p className="text-white/60">Could not load your weakness profile just now.</p>
      </Card>
    )
  }

  if (!profile) return <Spinner />

  if (profile.insufficient_data) {
    return (
      <Card className="p-6">
        <p className="font-semibold text-white">Not enough evidence yet</p>
        <p className="mt-2 text-sm text-white/60">
          {profile.total_mistakes === 0
            ? 'Review some words and any mistakes will show up here.'
            : `${profile.total_mistakes} mistake${profile.total_mistakes === 1 ? '' : 's'} recorded so far — not enough for a pattern worth acting on.`}
        </p>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-white/50">
        Based on {profile.total_mistakes} recorded mistake{profile.total_mistakes === 1 ? '' : 's'}.
      </p>

      {profile.categories.length > 0 && (
        <div>
          <h2 className="mb-3 font-display text-xl font-bold text-white">Where mistakes cluster</h2>
          <div className="flex flex-col gap-2">
            {profile.categories.map((c) => (
              <Card key={c.category} className="flex items-center justify-between p-4">
                <span className="text-white">{label(c.category)}</span>
                <span className="text-sm text-white/60">
                  {c.occurrences}× · {Math.round(c.share * 100)}%
                </span>
              </Card>
            ))}
          </div>
        </div>
      )}

      {profile.confused_pairs.length > 0 && (
        <div>
          <h2 className="mb-3 font-display text-xl font-bold text-white">Words you mix up</h2>
          <div className="flex flex-col gap-2">
            {profile.confused_pairs.map((p) => (
              <Card
                key={`${p.word_id}-${p.confused_with_word_id}`}
                className="flex items-center justify-between p-4"
              >
                <span className="text-white">
                  {/* A deleted word leaves the mistake intact but nameless. Saying
                      so beats rendering an empty gap the reader has to interpret. */}
                  {p.word_term ?? 'a deleted word'} <span className="text-white/40">vs</span>{' '}
                  {p.confused_with_term ?? 'a deleted word'}
                </span>
                <span className="text-sm text-white/60">{p.occurrences}×</span>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
