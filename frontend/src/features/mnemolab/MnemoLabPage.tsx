import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { groupsApi, mnemonicsApi, wordsApi } from '../../lib/api'
import type { MnemonicNote, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icon } from '../../components/ui/Icon'
import { Spinner } from '../../components/ui/Spinner'
import { Textarea } from '../../components/ui/Textarea'

export function MnemoLabPage() {
  const { wordId } = useParams()
  const navigate = useNavigate()
  const [words, setWords] = useState<Word[] | null>(null)
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<Word | null>(null)
  const [notes, setNotes] = useState<MnemonicNote[]>([])
  const [draft, setDraft] = useState('')

  useEffect(() => {
    groupsApi.list().then(async (groups) => {
      const allWords = (await Promise.all(groups.map((g) => groupsApi.words(g.id)))).flat()
      setWords(allWords)
    })
  }, [])

  const hardWords = useMemo(() => {
    if (!words) return []
    return [...words]
      .filter((w) => w.review_state.strength < 70)
      .filter((w) => w.term.toLowerCase().includes(filter.toLowerCase()))
      .sort((a, b) => a.review_state.strength - b.review_state.strength)
  }, [words, filter])

  useEffect(() => {
    if (wordId && words) {
      const w = words.find((x) => x.id === Number(wordId))
      if (w) selectWord(w)
    } else if (!wordId && hardWords.length > 0 && !selected) {
      selectWord(hardWords[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wordId, words])

  function selectWord(w: Word) {
    setSelected(w)
    setDraft(w.mnemonic ?? '')
    mnemonicsApi.list(w.id).then(setNotes)
    navigate(`/mnemolab/${w.id}`, { replace: true })
  }

  async function saveMnemonic() {
    if (!selected) return
    const updated = await wordsApi.update(selected.id, {
      term: selected.term,
      target_language: selected.target_language,
      translations: selected.translations,
      example_sentence: selected.example_sentence,
      mnemonic: draft || null,
      category: selected.category,
    })
    setSelected(updated)
    setWords((all) => all?.map((w) => (w.id === updated.id ? updated : w)) ?? null)
  }

  async function shareToGallery() {
    if (!selected || !draft.trim()) return
    const note = await mnemonicsApi.add(selected.id, draft)
    setNotes((n) => [note, ...n])
  }

  async function vote(note: MnemonicNote, upvote: boolean) {
    if (!selected) return
    const updated = await mnemonicsApi.vote(selected.id, note.id, upvote)
    setNotes((all) => all.map((n) => (n.id === updated.id ? updated : n)).sort((a, b) => b.score - a.score))
  }

  if (!words) return <Spinner />

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-6 overflow-hidden">
      <aside className="flex w-80 flex-shrink-0 flex-col gap-4 overflow-hidden rounded-lg bg-surface p-6">
        <h2 className="font-display text-2xl font-bold text-white">Hard words</h2>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter hard words..."
          className="h-11 rounded-lg border-none bg-canvas-dark px-4 text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <div className="flex flex-1 flex-col gap-2 overflow-y-auto">
          {hardWords.length === 0 && <p className="p-4 text-sm text-white/40">No struggling words right now — nice work.</p>}
          {hardWords.map((w) => (
            <button
              key={w.id}
              onClick={() => selectWord(w)}
              className={`flex items-center gap-4 rounded-lg p-4 text-left transition-colors ${selected?.id === w.id ? 'border border-primary/50 bg-primary/20' : 'hover:bg-white/5'}`}
            >
              <div className={`flex size-12 flex-shrink-0 items-center justify-center rounded-lg bg-canvas-dark ${selected?.id === w.id ? 'text-primary' : 'text-white/60'}`}>
                <Icon name="label" />
              </div>
              <div>
                <p className={`text-base font-semibold ${selected?.id === w.id ? 'text-primary' : 'text-white'}`}>{w.term}</p>
                <p className="text-sm text-white/40">Strength: {w.review_state.strength}</p>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex-1 overflow-y-auto">
        {!selected ? (
          <div className="flex h-full items-center justify-center text-white/30">Select a word to build a mnemonic.</div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-8 pb-8">
            <h1 className="font-display text-5xl font-bold text-primary">{selected.term}</h1>
            <Card className="p-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <p className="mb-1 text-sm text-white/40">Translation</p>
                  <p className="text-lg text-white">{selected.translations.join(', ') || '—'}</p>
                </div>
                <div>
                  <p className="mb-1 text-sm text-white/40">Strength score</p>
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 w-full rounded-full bg-white/10">
                      <div className="h-2.5 rounded-full bg-primary" style={{ width: `${selected.review_state.strength}%` }} />
                    </div>
                    <span className="font-medium text-white">{selected.review_state.strength}</span>
                  </div>
                </div>
                {selected.example_sentence && (
                  <div className="col-span-2">
                    <p className="mb-1 text-sm text-white/40">Example sentence</p>
                    <p className="text-lg italic text-white">{selected.example_sentence}</p>
                  </div>
                )}
              </div>
            </Card>

            <Card className="p-6">
              <label className="mb-2 block text-xl font-bold text-white">Create your mnemonic</label>
              <Textarea rows={5} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="A funny, vivid, or emotional image..." />
              <p className="mt-2 text-sm text-white/40">Use funny, vivid, or emotional imagery — it boosts recall.</p>
              <div className="mt-4 flex gap-3">
                <Button onClick={saveMnemonic}>Save mnemonic</Button>
                <Button variant="secondary" onClick={shareToGallery} disabled={!draft.trim()}>
                  Share to gallery
                </Button>
              </div>
            </Card>

            <Card className="p-6">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xl font-bold text-white">Mnemonic gallery for &ldquo;{selected.term}&rdquo;</h3>
                <span className="flex items-center gap-1 rounded-full bg-white/5 px-2 py-1 text-xs text-white/40" title="AI-generated suggestions are not available in this build — no LLM provider is configured.">
                  <Icon name="info" className="text-sm" /> AI suggestions unavailable
                </span>
              </div>
              <div className="flex flex-col gap-4">
                {notes.length === 0 && <p className="text-sm text-white/40">No mnemonics yet — be the first to share one.</p>}
                {notes.map((note) => (
                  <div key={note.id} className="rounded-lg border border-white/10 bg-canvas-dark p-4">
                    <p className="text-white/80">{note.text}</p>
                    <div className="mt-3 flex items-center justify-between text-sm">
                      <span className="flex items-center gap-2 text-white/40">
                        <Icon name="person" className="text-base" /> User #{note.author_id}
                      </span>
                      <div className="flex items-center gap-4">
                        <button onClick={() => vote(note, true)} className="flex items-center gap-1 text-white/40 hover:text-primary">
                          <Icon name="thumb_up" className="text-base" /> {note.upvotes}
                        </button>
                        <button onClick={() => vote(note, false)} className="flex items-center gap-1 text-white/40 hover:text-white">
                          <Icon name="thumb_down" className="text-base" /> {note.downvotes}
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Button variant="ghost" icon="hub" onClick={() => navigate(`/mindmap/${selected.id}`)}>
              Explore word associations
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
