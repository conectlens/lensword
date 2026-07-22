import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { settingsApi } from '../../lib/api'
import type { ProfileOverview } from '../../lib/types'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

export function ProfilePage() {
  const { user } = useAuth()
  const [overview, setOverview] = useState<ProfileOverview | null>(null)

  useEffect(() => {
    settingsApi.profile().then(setOverview)
  }, [])

  if (!overview) return <Spinner />

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8">
      <div className="flex items-center gap-6">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary/20 text-3xl font-bold text-primary">
          {user?.username?.[0]?.toUpperCase()}
        </div>
        <div>
          <h1 className="font-display text-3xl font-bold text-white">{user?.username}</h1>
          <p className="text-white/50">{user?.email}</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card className="p-6 text-center">
          <p className="text-3xl font-black text-white">{overview.user.total_words_learned}</p>
          <p className="mt-1 text-sm text-white/50">Words learned</p>
        </Card>
        <Card className="p-6 text-center">
          <p className="text-3xl font-black text-white">{Math.round(overview.user.total_study_seconds / 3600)}h</p>
          <p className="mt-1 text-sm text-white/50">Study time</p>
        </Card>
        <Card className="p-6 text-center">
          <p className="text-3xl font-black text-primary">{overview.user.streak_days}</p>
          <p className="mt-1 text-sm text-white/50">Day streak</p>
        </Card>
      </div>

      <div>
        <h2 className="mb-4 font-display text-xl font-bold text-white">Badges</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
          {overview.badges.map((b) => (
            <Card key={b.code} className={`flex flex-col items-center gap-2 p-5 text-center ${b.earned ? '' : 'opacity-30'}`}>
              <Icon name={b.icon} className={`text-3xl ${b.earned ? 'text-primary' : 'text-white/50'}`} />
              <p className="text-sm font-semibold text-white">{b.name}</p>
              <p className="text-xs text-white/40">{b.description}</p>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}
