import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { wordsApi } from '../../lib/api'
import type { Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'

type Kind = 'synonym' | 'antonym' | 'topic'

const KIND_LABEL: Record<Kind, string> = { synonym: 'Synonyms', antonym: 'Antonyms', topic: 'Topics' }

export function MindMapPage() {
  const { wordId } = useParams()
  const navigate = useNavigate()
  const [word, setWord] = useState<Word | null>(null)
  const [draft, setDraft] = useState<Record<Kind, string>>({ synonym: '', antonym: '', topic: '' })

  function load() {
    if (wordId) wordsApi.get(Number(wordId)).then(setWord)
  }
  useEffect(load, [wordId])

  if (!word) return <Spinner />

  const nodes: { kind: Kind; value: string }[] = [
    ...word.synonyms.map((v) => ({ kind: 'synonym' as Kind, value: v })),
    ...word.antonyms.map((v) => ({ kind: 'antonym' as Kind, value: v })),
    ...word.topics.map((v) => ({ kind: 'topic' as Kind, value: v })),
  ]

  async function addAssociation(kind: Kind, e: FormEvent) {
    e.preventDefault()
    const value = draft[kind].trim()
    if (!value) return
    const updated = await wordsApi.updateAssociations(word!.id, [{ kind, value }], [])
    setWord(updated)
    setDraft((d) => ({ ...d, [kind]: '' }))
  }

  async function removeAssociation(kind: Kind, value: string) {
    const updated = await wordsApi.updateAssociations(word!.id, [], [{ kind, value }])
    setWord(updated)
  }

  const radius = 260
  const angleStep = nodes.length > 0 ? (2 * Math.PI) / nodes.length : 0

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      <div className="relative flex-1 overflow-hidden rounded-lg bg-surface">
        <button onClick={() => navigate(-1)} className="absolute left-4 top-4 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-black/20 text-white hover:bg-black/40">
          <Icon name="arrow_back" />
        </button>
        <div className="relative flex h-full w-full items-center justify-center">
          {nodes.map((node, i) => {
            const angle = angleStep * i - Math.PI / 2
            const x = Math.cos(angle) * radius
            const y = Math.sin(angle) * radius
            return (
              <div key={`${node.kind}-${node.value}`}>
                <svg className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-1 overflow-visible" style={{ width: 1 }}>
                  <line x1={0} y1={0} x2={x} y2={y} stroke="#3f3f3f" strokeWidth={2} />
                </svg>
                <div
                  className="group absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-lg bg-canvas-dark px-4 py-2.5 shadow-md"
                  style={{ transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))` }}
                >
                  <p className="whitespace-nowrap text-white">{node.value}</p>
                  <button
                    onClick={() => removeAssociation(node.kind, node.value)}
                    className="absolute -right-2 -top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-danger text-white group-hover:flex"
                  >
                    <Icon name="close" className="text-xs" />
                  </button>
                </div>
              </div>
            )
          })}
          <div className="relative z-20 rounded-lg bg-primary px-8 py-5 shadow-lg">
            <h1 className="text-2xl font-bold text-ink sm:text-4xl">{word.term}</h1>
          </div>
        </div>
      </div>

      <aside className="flex w-80 flex-shrink-0 flex-col overflow-y-auto rounded-lg bg-surface p-6">
        <h2 className="mb-6 text-xl font-bold text-white">
          Associations for <span className="text-primary">{word.term}</span>
        </h2>
        {(['synonym', 'antonym', 'topic'] as Kind[]).map((kind) => (
          <div key={kind} className="mb-6">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/50">{KIND_LABEL[kind]}</h3>
            <div className="mb-3 space-y-2">
              {word[`${kind}s` as 'synonyms' | 'antonyms' | 'topics'].length === 0 && (
                <p className="text-sm text-white/30">None yet</p>
              )}
              {word[`${kind}s` as 'synonyms' | 'antonyms' | 'topics'].map((v) => (
                <div key={v} className="flex items-center justify-between rounded-lg bg-canvas-dark p-3 text-white/90">
                  {v}
                  <button onClick={() => removeAssociation(kind, v)} className="text-white/30 hover:text-danger">
                    <Icon name="close" className="text-base" />
                  </button>
                </div>
              ))}
            </div>
            <form onSubmit={(e) => addAssociation(kind, e)} className="flex gap-2">
              <input
                value={draft[kind]}
                onChange={(e) => setDraft((d) => ({ ...d, [kind]: e.target.value }))}
                placeholder={`Add a ${kind}`}
                className="h-9 flex-1 rounded-lg border border-white/10 bg-canvas-dark px-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <Button type="submit" size="sm" variant="secondary">
                Add
              </Button>
            </form>
          </div>
        ))}
      </aside>
    </div>
  )
}
