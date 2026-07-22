import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { groupsApi, reviewApi } from '../../lib/api'
import type { Group } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { ProgressRing } from '../../components/ui/ProgressRing'
import { Spinner } from '../../components/ui/Spinner'

const DAY_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function DashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [weekly, setWeekly] = useState<Record<string, number> | null>(null)

  useEffect(() => {
    groupsApi.list().then(setGroups)
    reviewApi.weeklyProgress().then((r) => setWeekly(r.counts_by_day))
  }, [])

  if (!groups || !weekly) return <Spinner />

  const dueCount = groups.reduce((sum, g) => sum + g.due_count, 0)
  const totalWords = groups.reduce((sum, g) => sum + g.word_count, 0)
  const masteredWords = groups.reduce((sum, g) => sum + g.mastered_count, 0)
  const weakGroup = [...groups].sort((a, b) => b.due_count - a.due_count)[0]
  const maxDaily = Math.max(1, ...Object.values(weekly))

  function startQuickReview() {
    navigate('/review?mode=standard')
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-3xl font-bold text-white lg:text-4xl">
          Hi, {user?.username}. Ready to lock in today&apos;s words?
        </h1>
        <div className="mt-4">
          <Button size="lg" icon="bolt" onClick={startQuickReview} disabled={dueCount === 0}>
            Start review session
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:gap-8">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Card className="p-6">
            <div className="flex flex-col items-center gap-6 sm:flex-row">
              <ProgressRing percent={totalWords ? (dueCount / totalWords) * 100 : 0} value={dueCount} label="Words" />
              <div className="flex w-full flex-col items-center gap-2 text-center sm:items-start sm:text-left">
                <p className="font-display text-xl font-bold text-white">Today&apos;s review</p>
                <p className="text-white/60">
                  {dueCount > 0 ? `You have ${dueCount} words due for review right now.` : 'Nothing due right now — nice work staying on top of it.'}
                </p>
                {dueCount > 0 && (
                  <Button size="sm" className="mt-2" onClick={startQuickReview}>
                    Start now
                  </Button>
                )}
              </div>
            </div>
          </Card>

          <Card className="p-6">
            <p className="font-display text-lg font-bold text-white">Weekly progress</p>
            <p className="text-sm text-white/50">Words reviewed in the last 7 days</p>
            <div className="mt-4 grid grid-flow-col items-end justify-items-center gap-3" style={{ minHeight: 160 }}>
              {DAY_ORDER.map((day) => {
                const count = weekly[day] ?? 0
                const heightPct = Math.max(4, (count / maxDaily) * 100)
                return (
                  <div key={day} className="flex h-full w-full flex-col items-center justify-end gap-2">
                    <span className="text-xs text-white/40">{count || ''}</span>
                    <div className="w-full rounded-t-md bg-primary" style={{ height: `${heightPct}%` }} />
                    <p className="text-xs font-bold text-white/50">{day}</p>
                  </div>
                )
              })}
            </div>
          </Card>

          <Card className="p-6">
            <p className="mb-4 font-display text-lg font-bold text-white">Quick actions</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <button onClick={() => navigate('/groups')} className="flex items-center justify-center gap-2 rounded-lg bg-canvas-dark p-4 text-white hover:bg-primary/20">
                <Icon name="add_circle" className="text-primary" /> Add word
              </button>
              <button onClick={() => navigate('/rooms')} className="flex items-center justify-center gap-2 rounded-lg bg-canvas-dark p-4 text-white hover:bg-primary/20">
                <Icon name="meeting_room" className="text-primary" /> Open Mind Palace
              </button>
              <button onClick={startQuickReview} className="flex items-center justify-center gap-2 rounded-lg bg-canvas-dark p-4 text-white hover:bg-primary/20">
                <Icon name="quiz" className="text-primary" /> Quick review
              </button>
            </div>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <Card className="flex flex-col gap-6 p-6">
            <div className="flex items-center gap-4">
              <div className="rounded-lg bg-primary/20 p-3">
                <Icon name="local_fire_department" className="text-3xl text-primary" />
              </div>
              <div>
                <p className="text-3xl font-black text-primary">{user?.streak_days ?? 0}</p>
                <p className="text-sm text-white/50">Day streak</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="rounded-lg bg-primary/20 p-3">
                <Icon name="school" className="text-3xl text-primary" />
              </div>
              <div>
                <p className="text-3xl font-black text-white">{masteredWords}</p>
                <p className="text-sm text-white/50">Words mastered</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="rounded-lg bg-primary/20 p-3">
                <Icon name="timer" className="text-3xl text-primary" />
              </div>
              <div>
                <p className="text-3xl font-black text-white">{Math.round((user?.total_study_seconds ?? 0) / 3600)}h</p>
                <p className="text-sm text-white/50">Total study time</p>
              </div>
            </div>
          </Card>

          {weakGroup && weakGroup.due_count > 0 && (
            <Card className="p-6">
              <div className="flex items-start gap-4">
                <Icon name="lightbulb" className="mt-1 text-3xl text-primary" />
                <div>
                  <p className="font-display text-lg font-bold text-white">Suggested action</p>
                  <p className="mt-1 text-white/60">
                    You have <span className="font-bold text-white">{weakGroup.due_count} words</span> due in &lsquo;{weakGroup.name}&rsquo;.
                  </p>
                </div>
              </div>
              <Button size="sm" className="mt-4 w-full" onClick={startQuickReview}>
                Review now
              </Button>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
