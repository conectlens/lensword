import { useEffect, useState } from 'react'
import { adminApi } from '../../lib/api'
import type { AdminStats, User } from '../../lib/types'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

export function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [users, setUsers] = useState<User[] | null>(null)
  const [search, setSearch] = useState('')

  function load(q?: string) {
    adminApi.stats().then(setStats)
    adminApi.users(q).then((r) => setUsers(r.users))
  }

  useEffect(() => load(), [])

  async function handleSuspend(user: User) {
    if (user.is_active) await adminApi.suspend(user.id)
    else await adminApi.reactivate(user.id)
    load(search)
  }

  async function handleDelete(user: User) {
    if (!confirm(`Permanently delete ${user.username} and all their data? This cannot be undone.`)) return
    await adminApi.remove(user.id)
    load(search)
  }

  if (!stats || !users) return <Spinner />

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-3xl font-bold text-white">Admin dashboard</h1>
        <p className="text-white/50">A snapshot of LensWord&apos;s real usage.</p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total users" value={stats.total_users} />
        <StatCard label="New users (30d)" value={stats.new_users_last_30_days} />
        <StatCard label="Words learned" value={stats.total_words_learned} />
        <StatCard
          label="Active sessions (1h)"
          value={stats.active_sessions_last_hour}
          note="Not tracked yet — needs a live-session heartbeat"
        />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 p-6">
          <h2 className="font-display text-xl font-bold text-white">All users</h2>
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              load(e.target.value)
            }}
            placeholder="Search users..."
            className="h-10 rounded-lg border border-white/10 bg-white/5 px-4 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/10 text-white/40">
              <tr>
                <th className="p-4 font-medium">User</th>
                <th className="p-4 font-medium">Joined</th>
                <th className="p-4 font-medium">Status</th>
                <th className="p-4 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
                  <td className="p-4">
                    <p className="font-medium text-white">{u.username}</p>
                    <p className="text-white/40">{u.email}</p>
                  </td>
                  <td className="p-4 text-white/60">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="p-4">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${u.is_active ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                      {u.is_active ? 'Active' : 'Suspended'}
                    </span>
                  </td>
                  <td className="p-4">
                    <div className="flex justify-end gap-1">
                      <button onClick={() => handleSuspend(u)} className="flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-white/10 hover:text-white" title={u.is_active ? 'Suspend' : 'Reactivate'}>
                        <Icon name={u.is_active ? 'block' : 'play_circle'} />
                      </button>
                      <button onClick={() => handleDelete(u)} className="flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-red-500/20 hover:text-red-400" title="Delete">
                        <Icon name="delete" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function StatCard({ label, value, note }: { label: string; value: number; note?: string }) {
  return (
    <Card className="flex flex-col gap-1 p-6">
      <p className="text-white/60">{label}</p>
      <p className="text-3xl font-bold text-white">{value.toLocaleString()}</p>
      {note && <p className="mt-1 text-xs text-white/30">{note}</p>}
    </Card>
  )
}
