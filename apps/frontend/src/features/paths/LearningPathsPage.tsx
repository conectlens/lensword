import { useEffect, useState } from 'react'
import { groupsApi, learningPathsApi } from '../../lib/api'
import type { Group, LearningPath, PathMilestone } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

/**
 * Turning a stated goal into milestones you can tell you have finished
 * (issue #137).
 *
 * Every number here is measured from the learner's own vocabulary at read
 * time. Nothing about progress is stored, so the bar cannot disagree with the
 * word list it is describing — and deleting words moves it back, which is the
 * case a saved percentage gets wrong.
 *
 * Generation reports three states rather than throwing. A provider switched
 * off and a provider temporarily down need different responses from the
 * learner: one is a setting, the other is worth retrying.
 */

function MilestoneCard({ milestone, isNext }: { milestone: PathMilestone; isNext: boolean }) {
  const percent = Math.round(milestone.share * 100)
  return (
    <Card className={`p-4 ${isNext ? 'border-primary/40' : ''}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-white">
          {milestone.complete && <Icon name="check" className="mr-2 text-emerald-300" />}
          {milestone.title}
        </span>
        <span className="text-sm text-white/50">
          {/* Held and mastered are different claims — a path reporting only the
              first would overstate what the learner can actually do. */}
          {milestone.words_held}/{milestone.target_word_count} words
          {milestone.words_mastered > 0 && ` · ${milestone.words_mastered} mastered`}
        </span>
      </div>

      {milestone.description && (
        <p className="mt-1 text-sm text-white/60">{milestone.description}</p>
      )}

      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${milestone.complete ? 'bg-emerald-400' : 'bg-primary'}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      <p className="mt-2 text-xs text-white/40">
        Topic: {milestone.topic}
        {milestone.cefr_level && ` · ${milestone.cefr_level}`}
      </p>
    </Card>
  )
}

function PathCard({ path, onDelete }: { path: LearningPath; onDelete: (id: number) => void }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-xl font-bold text-white">{path.goal}</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-white/50">
            {path.completed_count}/{path.milestones.length} milestones
          </span>
          <Button size="sm" variant="ghost" onClick={() => onDelete(path.id)}>
            Delete
          </Button>
        </div>
      </div>

      {/* Named explicitly rather than left for the learner to find by scanning
          — a plan's value is knowing which step you are on. */}
      {path.next_milestone ? (
        <p className="text-sm text-white/60">Next: {path.next_milestone.title}</p>
      ) : (
        <p className="text-sm text-emerald-300">Every milestone met.</p>
      )}

      <div className="flex flex-col gap-2">
        {path.milestones.map((milestone) => (
          <MilestoneCard
            key={milestone.position}
            milestone={milestone}
            isNext={path.next_milestone?.position === milestone.position}
          />
        ))}
      </div>
    </div>
  )
}

export function LearningPathsPage() {
  const [paths, setPaths] = useState<LearningPath[] | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [goal, setGoal] = useState('')
  const [language, setLanguage] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    learningPathsApi.list().then(setPaths).catch(() => setPaths([]))
    groupsApi.list().then((all) => {
      setGroups(all)
      if (all[0]) setLanguage(all[0].target_language)
    })
  }, [])

  async function generate() {
    if (!goal.trim() || !language) return
    setBusy(true)
    setNotice(null)
    try {
      const result = await learningPathsApi.generate(goal.trim(), language)
      if (result.status === 'ok' && result.path) {
        setPaths((current) => [result.path as LearningPath, ...(current ?? [])])
        setGoal('')
      } else {
        // The server's own wording. It distinguishes "not configured" from
        // "temporarily down", and rewriting it here would lose that.
        setNotice(result.detail ?? 'Could not generate a path.')
      }
    } catch {
      setNotice('Could not generate a path.')
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: number) {
    await learningPathsApi.remove(id)
    setPaths((current) => current?.filter((path) => path.id !== id) ?? null)
  }

  if (!paths) return <Spinner />

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8">
      <div>
        <h1 className="font-display text-3xl font-bold text-white">Learning paths</h1>
        <p className="text-white/50">
          Say what you want to be able to do. Progress is counted from the words you actually have.
        </p>
      </div>

      <Card className="flex flex-col gap-3 p-6">
        <input
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="e.g. Order food confidently in Spain"
          aria-label="Your goal"
          maxLength={500}
          className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-white"
        />
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-white/70">
            Language
            <select
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              aria-label="Target language"
              className="ml-2 rounded bg-white/10 p-2 text-white"
            >
              {[...new Set(groups.map((group) => group.target_language))].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <Button loading={busy} disabled={!goal.trim() || !language} onClick={() => void generate()}>
            Generate a path
          </Button>
        </div>
        {notice && (
          <p role="alert" className="text-sm text-amber-200">
            {notice}
          </p>
        )}
      </Card>

      {paths.length === 0 && (
        <p className="text-white/40">No paths yet. Describe a goal above to get one.</p>
      )}

      {paths.map((path) => (
        <PathCard key={path.id} path={path} onDelete={(id) => void remove(id)} />
      ))}
    </div>
  )
}
