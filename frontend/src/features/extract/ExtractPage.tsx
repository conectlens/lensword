import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { extractionApi, groupsApi } from '../../lib/api'
import type { ExtractedCandidate, ExtractVocabularyResult } from '../../lib/api'
import type { Group } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

export function ExtractPage() {
  const { groupId } = useParams()
  const navigate = useNavigate()
  const [group, setGroup] = useState<Group | null>(null)
  const [text, setText] = useState('')
  const [minLevel, setMinLevel] = useState('')
  const [result, setResult] = useState<ExtractVocabularyResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  useEffect(() => { groupsApi.list().then((groups) => setGroup(groups.find((item) => item.id === Number(groupId)) ?? null)) }, [groupId])
  if (!group) return <Spinner />
  const currentGroup = group

  async function extract() {
    setLoading(true)
    try {
      const next = await extractionApi.extract(currentGroup.id, text, currentGroup.target_language, minLevel || null)
      setResult(next)
      if (next.status === 'ok') setSelected(new Set(next.items.map((item) => item.term)))
    } finally { setLoading(false) }
  }

  async function save() {
    if (!result || result.status !== 'ok') return
    await Promise.all(result.items.filter((item) => selected.has(item.term)).map((item) => groupsApi.addWord(currentGroup.id, {
      term: item.term, target_language: currentGroup.target_language, translations: item.translations,
      example_sentence: item.examples[0] ?? null, cefr_level: item.cefr_level,
    })))
    navigate(`/groups/${currentGroup.id}`)
  }

  return <div className="mx-auto flex max-w-3xl flex-col gap-6">
    <div><h1 className="font-display text-3xl font-bold text-white">Extract vocabulary</h1><p className="text-white/50">Source language is auto-detected from the text. Review every suggestion before saving.</p></div>
    <Card className="flex flex-col gap-4 p-6">
      <textarea value={text} onChange={(event) => setText(event.target.value)} rows={10} placeholder="Paste a passage…" className="w-full rounded-lg border border-white/10 bg-white/5 p-3 text-white" />
      <label className="text-sm text-white/70">Minimum CEFR level <select value={minLevel} onChange={(event) => setMinLevel(event.target.value)} className="ml-2 rounded bg-white/10 p-2 text-white"><option value="">Any</option>{['A1','A2','B1','B2','C1','C2'].map((level) => <option key={level} value={level}>{level}</option>)}</select></label>
      <Button onClick={extract} loading={loading} disabled={!text.trim()}>Extract with AI</Button>
    </Card>
    {result?.status === 'disabled' && <p className="text-amber-200">AI is not configured for this deployment.</p>}
    {result?.status === 'unavailable' && <p className="text-red-300">{result.detail}</p>}
    {result?.status === 'ok' && <Card className="flex flex-col gap-3 p-6">
      {result.items.map((item: ExtractedCandidate) => <label key={item.term} className="flex gap-3 rounded border border-white/10 p-3 text-white"><input type="checkbox" checked={selected.has(item.term)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(item.term)) next.delete(item.term); else next.add(item.term); return next })} /><span><strong>{item.term}</strong> · {item.translations.join(', ')} {item.cefr_level && <em className="text-white/50">{item.cefr_level}</em>}<br/><small className="text-white/60">{item.examples[0]}</small></span></label>)}
      <Button onClick={save} disabled={selected.size === 0}>Save selected cards</Button>
    </Card>}
  </div>
}
