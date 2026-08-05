import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { groupsApi, roomsApi } from '../../lib/api'
import type { Group, Room } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { EmptyState } from '../../components/ui/EmptyState'
import { Icon } from '../../components/ui/Icon'
import { Modal } from '../../components/ui/Modal'
import { Select } from '../../components/ui/Select'
import { Input } from '../../components/ui/Input'
import { Spinner } from '../../components/ui/Spinner'

const ROOM_ICONS = ['meeting_room', 'local_library', 'restaurant', 'science', 'bed', 'work', 'flight']

export function RoomsPage() {
  const navigate = useNavigate()
  const [rooms, setRooms] = useState<Room[] | null>(null)
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  function load() {
    roomsApi.list().then(setRooms)
    groupsApi.list().then(setGroups)
  }

  useEffect(load, [])

  if (!rooms || !groups) return <Spinner />

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col items-center gap-6 text-center">
        <div>
          <h1 className="font-display text-4xl font-black tracking-tight text-white md:text-5xl">Mind Palace</h1>
          <p className="mt-2 text-white/60">Visualize your vocabulary inside memory rooms.</p>
        </div>
        <Button size="lg" icon="add" onClick={() => setShowCreate(true)} disabled={groups.length === 0}>
          {groups.length === 0 ? 'Create a group first' : 'Create a room'}
        </Button>
      </div>

      {rooms.length === 0 ? (
        <EmptyState
          icon="space_dashboard"
          title="Your palace awaits"
          description="You have no memory rooms yet. Create your first one to start placing words spatially."
          action={
            groups.length > 0 ? (
              <Button icon="add" onClick={() => setShowCreate(true)}>Create your first room</Button>
            ) : (
              <Button onClick={() => navigate('/groups')}>Go create a group</Button>
            )
          }
        />
      ) : (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-6">
          {rooms.map((room) => {
            const pct = Math.round(room.placements.length && room.group_word_count ? (room.placements.length / room.group_word_count) * 100 : 0)
            return (
              <Card key={room.id} className="flex flex-col gap-4 p-6 transition-transform hover:scale-[1.02]">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-black/20 text-primary">
                    <Icon name={room.icon} />
                  </div>
                  <h2 className="font-display text-lg font-bold text-white">{room.name}</h2>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex justify-between text-sm">
                    <p className="text-white/60">Words placed</p>
                    <p className="font-medium text-white">{room.placements.length} / {room.group_word_count}</p>
                  </div>
                  <div className="h-2 w-full rounded-full bg-black/20">
                    <div className="h-2 rounded-full bg-primary" style={{ width: `${pct}%` }} />
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => navigate(`/rooms/${room.id}`)}>
                  Open room
                </Button>
              </Card>
            )
          })}
          <button
            onClick={() => setShowCreate(true)}
            className="flex flex-1 flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed border-white/20 p-6 text-center transition-colors hover:border-primary hover:bg-white/5"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface text-primary">
              <Icon name="add" className="text-3xl" />
            </div>
            <div>
              <p className="font-display text-lg font-bold text-white">Create a new room</p>
              <p className="text-sm text-white/50">Expand your palace</p>
            </div>
          </button>
        </div>
      )}

      {showCreate && (
        <CreateRoomModal
          groups={groups}
          onClose={() => setShowCreate(false)}
          onCreated={(room) => {
            setShowCreate(false)
            navigate(`/rooms/${room.id}`)
          }}
        />
      )}
    </div>
  )
}

function CreateRoomModal({ groups, onClose, onCreated }: { groups: Group[]; onClose: () => void; onCreated: (room: Room) => void }) {
  const [name, setName] = useState('')
  const [groupId, setGroupId] = useState(groups[0]?.id ?? 0)
  const [icon, setIcon] = useState(ROOM_ICONS[0])
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const room = await roomsApi.create(groupId, name, icon)
      onCreated(room)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title="Create a memory room" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input label="Room name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., The Library" />
        <Select
          label="Which group's words will live here?"
          value={String(groupId)}
          onChange={(e) => setGroupId(Number(e.target.value))}
          options={groups.map((g) => ({ value: String(g.id), label: `${g.name} (${g.word_count} words)` }))}
        />
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-white">Icon</span>
          <div className="flex flex-wrap gap-2">
            {ROOM_ICONS.map((i) => (
              <button
                type="button"
                key={i}
                onClick={() => setIcon(i)}
                className={`flex h-11 w-11 items-center justify-center rounded-lg border ${icon === i ? 'border-primary bg-primary/20 text-primary' : 'border-white/10 text-white/50 hover:bg-white/5'}`}
              >
                <Icon name={i} />
              </button>
            ))}
          </div>
        </div>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row-reverse">
          <Button type="submit" loading={loading} disabled={!name.trim() || !groupId}>
            Create room
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </Modal>
  )
}
