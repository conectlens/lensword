import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { groupsApi, wordsApi } from '../../lib/api'
import type { Group, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { EmptyState } from '../../components/ui/EmptyState'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { StatusChip } from '../../components/ui/StatusChip'

export function GroupDetailPage() {
  const { groupId } = useParams()
  const navigate = useNavigate()
  const [group, setGroup] = useState<Group | null>(null)
  const [words, setWords] = useState<Word[] | null>(null)
  const [sortBy, setSortBy] = useState<'strength' | 'term' | 'next_review'>('strength')

  function load() {
    if (!groupId) return
    groupsApi.list().then((all) => setGroup(all.find((g) => g.id === Number(groupId)) ?? null))
    groupsApi.words(Number(groupId)).then(setWords)
  }

  useEffect(load, [groupId])

  if (!group || !words) return <Spinner />

  const sorted = [...words].sort((a, b) => {
    if (sortBy === 'term') return a.term.localeCompare(b.term)
    if (sortBy === 'next_review') return new Date(a.review_state.due_at).getTime() - new Date(b.review_state.due_at).getTime()
    return a.review_state.strength - b.review_state.strength
  })

  function startReview() {
    navigate(`/review?mode=standard&group=${group!.id}`)
  }

  async function deleteWord(wordId: number) {
    if (!confirm('Delete this word? This cannot be undone.')) return
    await wordsApi.remove(wordId)
    load()
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold text-white">{group.name}</h1>
          <p className="text-white/50">{group.target_language} · Group details and vocabulary list</p>
        </div>
        <div className="flex gap-3">
          <Button variant="secondary" icon="add" onClick={() => navigate(`/groups/${group.id}/words/new`)}>
            Add word
          </Button>
          <Button icon="bolt" onClick={startReview} disabled={group.due_count === 0}>
            Start review
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card className="p-4 text-center">
          <p className="text-2xl font-bold text-white">{group.word_count}</p>
          <p className="text-xs text-white/50">Total words</p>
        </Card>
        <Card className="p-4 text-center">
          <p className="text-2xl font-bold text-white">{group.mastered_count}</p>
          <p className="text-xs text-white/50">Mastered</p>
        </Card>
        <Card className="p-4 text-center">
          <p className="text-2xl font-bold text-primary">{group.due_count}</p>
          <p className="text-xs text-white/50">Due today</p>
        </Card>
        <Card className="p-4 text-center">
          <p className="text-2xl font-bold text-white">{group.last_reviewed_at ? new Date(group.last_reviewed_at).toLocaleDateString() : '—'}</p>
          <p className="text-xs text-white/50">Last reviewed</p>
        </Card>
      </div>

      {words.length === 0 ? (
        <EmptyState
          icon="menu_book"
          title="No words yet"
          description="Add your first word to start building this group's vocabulary."
          action={<Button icon="add" onClick={() => navigate(`/groups/${group.id}/words/new`)}>Add word</Button>}
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-white/10 p-4">
            <p className="font-display font-bold text-white">Word list</p>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white"
            >
              <option value="strength">Sort: Strength</option>
              <option value="term">Sort: A–Z</option>
              <option value="next_review">Sort: Next review</option>
            </select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="border-b border-white/10 text-sm text-white/40">
                <tr>
                  <th className="p-4 font-medium">Word</th>
                  <th className="p-4 font-medium">Translation</th>
                  <th className="p-4 font-medium">Status</th>
                  <th className="p-4 font-medium">Next review</th>
                  <th className="p-4 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((w) => (
                  <tr key={w.id} className="group border-b border-white/5 last:border-0 hover:bg-white/5">
                    <td className="p-4 text-white">{w.term}</td>
                    <td className="p-4 text-white/60">{w.translations.join(', ')}</td>
                    <td className="p-4">
                      <StatusChip status={w.review_state.status} />
                    </td>
                    <td className="p-4 text-white/60">
                      {w.review_state.repetitions === 0 ? 'Not studied' : new Date(w.review_state.due_at).toLocaleDateString()}
                    </td>
                    <td className="p-4">
                      <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100">
                        <Link
                          to={`/groups/${group.id}/words/${w.id}`}
                          className="flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-white/10 hover:text-white"
                        >
                          <Icon name="edit" />
                        </Link>
                        <button
                          onClick={() => deleteWord(w.id)}
                          className="flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-white/10 hover:text-red-400"
                        >
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
      )}
    </div>
  )
}
