import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { groupsApi } from '../../lib/api'
import { LANGUAGES, type Group, type SupportedLanguage } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { EmptyState } from '../../components/ui/EmptyState'
import { Input } from '../../components/ui/Input'
import { Select } from '../../components/ui/Select'
import { Modal } from '../../components/ui/Modal'
import { Spinner } from '../../components/ui/Spinner'

export function GroupsPage() {
  const navigate = useNavigate()
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  function load() {
    groupsApi.list().then(setGroups)
  }

  useEffect(load, [])

  if (!groups) return <Spinner />

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-display text-4xl font-bold text-white">Your groups</h1>
        <Button icon="add" onClick={() => setShowCreate(true)}>
          New group
        </Button>
      </div>

      {groups.length === 0 ? (
        <EmptyState
          icon="category"
          title="No groups yet"
          description="Create groups to organize your vocabulary and start learning new words today."
          action={<Button icon="add" onClick={() => setShowCreate(true)}>Create your first group</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {groups.map((g) => {
            const pct = g.word_count ? Math.round((g.mastered_count / g.word_count) * 100) : 0
            return (
              <Card key={g.id} className="flex flex-col gap-4 p-6 transition-shadow hover:shadow-primary/10">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-display text-xl font-semibold text-white">{g.name}</h3>
                    <p className="text-sm text-white/40">{g.target_language}</p>
                  </div>
                  {g.due_count > 0 && (
                    <span className="rounded-full bg-primary/20 px-2 py-1 text-xs font-medium text-primary">{g.due_count} due</span>
                  )}
                </div>
                <div className="space-y-1 text-sm text-white/50">
                  <p>{g.word_count} words</p>
                  <p>{g.last_reviewed_at ? `Last reviewed ${new Date(g.last_reviewed_at).toLocaleDateString()}` : 'Not reviewed yet'}</p>
                </div>
                <div className="h-2.5 w-full rounded-full bg-white/10">
                  <div className="h-2.5 rounded-full bg-primary" style={{ width: `${pct}%` }} />
                </div>
                <Button variant="secondary" size="sm" className="mt-1 w-full" onClick={() => navigate(`/groups/${g.id}`)}>
                  Open group
                </Button>
              </Card>
            )
          })}
        </div>
      )}

      {showCreate && (
        <CreateGroupModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            load()
          }}
        />
      )}
    </div>
  )
}

function CreateGroupModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState<SupportedLanguage>('Spanish')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await groupsApi.create(name, language)
      onCreated()
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title="Create new vocabulary group" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input label="Group name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., Spanish Verbs, Business English" />
        <Select
          label="Target language"
          value={language}
          onChange={(e) => setLanguage(e.target.value as SupportedLanguage)}
          options={LANGUAGES.map((l) => ({ value: l, label: l }))}
        />
        <div className="mt-2 flex flex-col gap-3 sm:flex-row-reverse">
          <Button type="submit" loading={loading} disabled={!name.trim()}>
            Create group
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </Modal>
  )
}
