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
  const [editing, setEditing] = useState<Group | null>(null)

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
                  <div className="flex items-center gap-2">
                    {g.due_count > 0 && (
                      <span className="rounded-full bg-primary/20 px-2 py-1 text-xs font-medium text-primary">{g.due_count} due</span>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      icon="edit"
                      aria-label={`Edit ${g.name}`}
                      onClick={() => setEditing(g)}
                    />
                  </div>
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

      {editing && (
        <EditGroupModal
          group={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            load()
          }}
        />
      )}
    </div>
  )
}

function EditGroupModal({
  group,
  onClose,
  onSaved,
}: {
  group: Group
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(group.name)
  const [language, setLanguage] = useState<SupportedLanguage>(group.target_language)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const languageChanged = language !== group.target_language

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await groupsApi.update(group.id, { name: name.trim(), target_language: language })
      onSaved()
    } catch {
      setError('Could not save those changes.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title="Edit group" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="Group name"
          required
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Select
          label="Target language"
          value={language}
          onValueChange={(next) => setLanguage(next as SupportedLanguage)}
          options={LANGUAGES.map((l) => ({ value: l, label: l }))}
        />

        {/* Said before saving, not after: words keep the language they were
            added with, so a group holding vocabulary in the old language is
            the expected outcome rather than a bug to discover later. */}
        {languageChanged && group.word_count > 0 && (
          <p className="text-sm text-white/50">
            The {group.word_count} {group.word_count === 1 ? 'word' : 'words'} already in this group
            stay marked as {group.target_language}. Only the group changes to {language}.
          </p>
        )}

        {error && (
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
        )}

        <div className="mt-2 flex flex-col gap-3 sm:flex-row-reverse">
          <Button type="submit" loading={loading} disabled={!name.trim()}>
            Save changes
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </Modal>
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
          onValueChange={(next) => setLanguage(next as SupportedLanguage)}
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
