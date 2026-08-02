import { useEffect, useState } from 'react'
import { settingsApi } from '../../lib/api'
import type { CefrProgress, LevelProgress } from '../../lib/types'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

/**
 * Progress across CEFR levels (issue #143).
 *
 * Deliberately does not show "your level is B2". It is the number everyone
 * wants and the one this data cannot support: a CEFR level describes what a
 * person can *do* in a language, and what we hold is which words are in their
 * deck and how well they recall them. Someone who added forty C1 words
 * yesterday is not C1.
 *
 * Words with no level recorded get their own row rather than being hidden or
 * distributed. Most decks are full of them, and totals that disagree with the
 * learner's own word count are the fastest way to lose their trust in the
 * whole screen.
 */

function LevelRow({ level }: { level: LevelProgress }) {
  const percent = Math.round(level.mastery_share * 100)
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-white">
          {level.level === 'unknown' ? 'No level recorded' : level.level}
        </span>
        <span className="text-sm text-white/60">
          {level.total === 0
            ? 'No words yet'
            : `${level.mastered}/${level.total} mastered · ${percent}%`}
        </span>
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
    </Card>
  )
}

export function CefrProgressTab() {
  const [progress, setProgress] = useState<CefrProgress | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    settingsApi.cefrProgress().then(setProgress).catch(() => setFailed(true))
  }, [])

  if (failed) {
    return (
      <Card className="p-6">
        <p className="text-white/60">Could not load your level progress just now.</p>
      </Card>
    )
  }

  if (!progress) return <Spinner />

  if (progress.total_words === 0) {
    return (
      <Card className="p-6">
        <p className="font-semibold text-white">No words yet</p>
        <p className="mt-2 text-sm text-white/60">
          Add some vocabulary and your progress across levels will appear here.
        </p>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-white/50">
        Mastery is measured against the words you have at each level — not against the level
        itself, which would mean claiming to know how big it is.
      </p>

      {progress.levels.map((level) => (
        <LevelRow key={level.level} level={level} />
      ))}

      {progress.unlevelled && (
        <>
          <p className="mt-2 text-sm text-white/50">
            These words have no CEFR level recorded, so they are counted here rather than folded
            into a level they might not belong to.
          </p>
          <LevelRow level={progress.unlevelled} />
        </>
      )}
    </div>
  )
}
