import { Suspense, lazy, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { roomsApi } from '../../lib/api'
import { isWebglAvailable } from '../../lib/roomSpace'
import type { Room, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

// three.js and its React bindings are large and used only here, so they are
// fetched when a room is actually opened in 3D rather than shipped to every
// page in the main bundle.
const RoomScene3D = lazy(() => import('./RoomScene3D'))

export function RoomDetailPage() {
  const { roomId } = useParams()
  const navigate = useNavigate()
  const [room, setRoom] = useState<Room | null>(null)
  const [words, setWords] = useState<Word[] | null>(null)
  const [draggingWordId, setDraggingWordId] = useState<number | null>(null)
  const [selectedWordId, setSelectedWordId] = useState<number | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)

  // Resolved once: the answer cannot change while the page is open, and
  // creating a probe canvas on every render would be wasteful.
  const webgl = useMemo(() => isWebglAvailable(), [])
  // 3D is the room's point (issue #339), so it is the default wherever it
  // can be drawn. The flat board stays reachable, and becomes the only view
  // when WebGL is unavailable — that is a fallback, not a preference.
  const [view, setView] = useState<'3d' | '2d'>(webgl ? '3d' : '2d')

  function load() {
    if (!roomId) return
    roomsApi.get(Number(roomId)).then(setRoom)
    roomsApi.words(Number(roomId)).then(setWords)
  }

  useEffect(load, [roomId])

  if (!room || !words) return <Spinner />

  const placedIds = new Set(room.placements.map((p) => p.word_id))
  const unplacedWords = words.filter((w) => !placedIds.has(w.id))
  const wordById = new Map(words.map((w) => [w.id, w]))

  async function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    if (draggingWordId == null || !canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    const xPercent = Math.max(2, Math.min(98, ((e.clientX - rect.left) / rect.width) * 100))
    const yPercent = Math.max(2, Math.min(98, ((e.clientY - rect.top) / rect.height) * 100))
    const updated = await roomsApi.place(room!.id, draggingWordId, xPercent, yPercent)
    setRoom(updated)
    setDraggingWordId(null)
  }

  async function placeAt(xPercent: number, yPercent: number) {
    if (selectedWordId == null) return
    setRoom(await roomsApi.place(room!.id, selectedWordId, xPercent, yPercent))
    setSelectedWordId(null)
  }

  async function removePlacement(wordId: number) {
    const updated = await roomsApi.unplace(room!.id, wordId)
    setRoom(updated)
  }

  async function deleteRoom() {
    if (!confirm(`Delete "${room!.name}"? This cannot be undone.`)) return
    await roomsApi.remove(room!.id)
    navigate('/rooms')
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-display text-3xl font-black text-white">{room.name}</p>
          <p className="text-white/50">Drag words onto the canvas to build memory anchors.</p>
        </div>
        {webgl && (
          <Button
            variant="ghost"
            icon={view === '3d' ? 'style' : 'explore'}
            onClick={() => setView((current) => (current === '3d' ? '2d' : '3d'))}
          >
            {view === '3d' ? 'Flat view' : '3D view'}
          </Button>
        )}
        <Button variant="ghost" icon="delete" onClick={deleteRoom}>
          Delete room
        </Button>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        {view === '3d' ? (
        <div className="relative flex-1 overflow-hidden rounded-lg bg-surface">
          <Suspense fallback={<Spinner />}>
            <RoomScene3D
              room={room}
              wordById={wordById}
              selectedWordId={selectedWordId}
              onPlace={placeAt}
              onRemove={removePlacement}
            />
          </Suspense>
          <p className="pointer-events-none absolute bottom-3 left-1/2 w-max max-w-[90%] -translate-x-1/2 rounded-lg bg-black/60 px-3 py-2 text-center text-xs text-white/70">
            {selectedWordId == null
              ? 'Pick a word from the list, then click the floor to place it. Drag to orbit.'
              : 'Click the floor to place it. Click a marker to remove it.'}
          </p>
        </div>
        ) : (
        <div
          ref={canvasRef}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          className="relative flex-1 overflow-hidden rounded-lg bg-surface"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)',
            backgroundSize: '32px 32px',
          }}
        >
          {room.placements.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-center text-white/30">
              <p className="max-w-xs">Drag a word from the list to place it here as a spatial memory anchor.</p>
            </div>
          )}
          {room.placements.map((p) => {
            const word = wordById.get(p.word_id)
            if (!word) return null
            return (
              <div
                key={p.word_id}
                className="group absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${p.x_percent}%`, top: `${p.y_percent}%` }}
                draggable
                onDragStart={() => setDraggingWordId(p.word_id)}
              >
                <div className="flex size-12 cursor-grab items-center justify-center rounded-lg border-2 border-primary bg-primary/20 shadow-lg transition-transform hover:scale-110 active:cursor-grabbing">
                  <Icon name="label" className="text-primary" />
                </div>
                <div className="pointer-events-none absolute bottom-full left-1/2 mb-2 w-max max-w-[10rem] -translate-x-1/2 rounded-lg bg-black px-3 py-2 text-sm text-white opacity-0 shadow-xl transition-opacity group-hover:opacity-100">
                  <p className="font-bold">{word.term}</p>
                  <p className="text-white/70">{word.translations[0]}</p>
                </div>
                <button
                  onClick={() => removePlacement(p.word_id)}
                  className="absolute -right-2 -top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-danger text-white group-hover:flex"
                  aria-label={`Remove ${word.term} from room`}
                >
                  <Icon name="close" className="text-xs" />
                </button>
              </div>
            )
          })}
        </div>
        )}

        <aside className="flex w-72 flex-shrink-0 flex-col overflow-hidden rounded-lg bg-surface">
          <div className="border-b border-white/10 p-4">
            <h3 className="font-bold text-white">{room.name} words</h3>
            <p className="text-sm text-white/40">
              {view === '3d' ? 'Select, then click the floor' : 'Drag to place'} ·{' '}
              {room.placements.length}/{words.length} placed
            </p>
            {/* Said rather than silently omitted: without this the 3D room
                the feature is named after simply would not be there, with
                nothing on screen explaining why. */}
            {!webgl && (
              <p className="mt-2 text-xs text-white/40">
                3D view is unavailable because this browser has no WebGL support. The flat board
                below places words in exactly the same spots.
              </p>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {unplacedWords.length === 0 ? (
              <p className="p-3 text-sm text-white/40">All words are placed. Nice work.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {unplacedWords.map((w) => (
                  // Selectable as well as draggable: a drag has no meaning
                  // against a 3D floor, and selecting then clicking is also
                  // the version that works from a keyboard.
                  <button
                    key={w.id}
                    type="button"
                    draggable
                    aria-pressed={selectedWordId === w.id}
                    onDragStart={() => setDraggingWordId(w.id)}
                    onClick={() => setSelectedWordId((current) => (current === w.id ? null : w.id))}
                    className={`flex cursor-grab items-center gap-3 rounded-lg border p-3 text-left active:cursor-grabbing ${
                      selectedWordId === w.id
                        ? 'border-primary bg-primary/30'
                        : 'border-primary/50 bg-primary/10'
                    }`}
                  >
                    <Icon name="label" className="text-primary" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-white">{w.term}</p>
                      <p className="text-xs text-white/50">{w.translations[0]}</p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
