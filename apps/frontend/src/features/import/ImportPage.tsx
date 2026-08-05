import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { groupsApi, importsApi } from '../../lib/api'
import type { Group } from '../../lib/types'
import type { ImportPreviewRecord } from '../../lib/api'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

export function ImportPage() {
  const { groupId } = useParams(); const navigate = useNavigate()
  const [group, setGroup] = useState<Group | null>(null); const [raw, setRaw] = useState('[\n  {"term": "hola", "translations": ["hello"]}\n]')
  const [enrich, setEnrich] = useState(true); const [records, setRecords] = useState<ImportPreviewRecord[] | null>(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(false)
  useEffect(() => { groupsApi.list().then((items) => setGroup(items.find((item) => item.id === Number(groupId)) ?? null)) }, [groupId])
  if (!group) return <Spinner />
  const currentGroup = group
  async function preview() { setLoading(true); setError(''); try { const parsed = JSON.parse(raw); if (!Array.isArray(parsed)) throw new Error('Provide a JSON array of vocabulary records.'); setRecords((await importsApi.preview(currentGroup.id, parsed, enrich)).records) } catch (value) { setError(value instanceof Error ? value.message : 'Could not parse records') } finally { setLoading(false) } }
  async function commit() { if (!records) return; setLoading(true); try { await importsApi.commit(currentGroup.id, records); navigate(`/groups/${currentGroup.id}`) } finally { setLoading(false) } }
  async function upload(file: File) { setLoading(true); setError(''); try { const parsed = await importsApi.parseFile(file); setRaw(JSON.stringify(parsed.records, null, 2)) } catch (value) { setError(value instanceof Error ? value.message : 'Could not parse file') } finally { setLoading(false) } }
  return <div className="mx-auto flex max-w-4xl flex-col gap-6"><div><h1 className="font-display text-3xl font-bold text-white">Import vocabulary</h1><p className="text-white/50">Upload CSV, TSV, JSON, or plain text; inspect cleanup results, then commit the reviewed cards.</p></div><Card className="flex flex-col gap-4 p-6"><input type="file" accept=".csv,.tsv,.json,.txt" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} className="text-sm text-white" /><textarea rows={12} value={raw} onChange={(event) => setRaw(event.target.value)} className="w-full rounded-lg border border-white/10 bg-white/5 p-3 font-mono text-sm text-white" /><label className="text-sm text-white/70"><input type="checkbox" checked={enrich} onChange={(event) => setEnrich(event.target.checked)} className="mr-2" />Fill missing fields with AI</label>{error && <p className="text-red-300">{error}</p>}<Button onClick={preview} loading={loading}>Preview import</Button></Card>{records && <Card className="flex flex-col gap-3 p-6"><h2 className="font-display text-xl text-white">Review import</h2>{records.map((record, index) => <div key={`${record.term}-${index}`} className="rounded border border-white/10 p-3 text-sm text-white"><strong>{record.term}</strong> · {record.translations.join(', ') || 'No translation'} <span className="ml-2 text-xs text-white/50">{record.status}{record.source_language !== 'Unknown' && ` · detected ${record.source_language}`}</span>{record.definition && <p className="mt-1 text-white/60">{record.definition}</p>}</div>)}<Button onClick={commit} loading={loading} disabled={!records.some((record) => record.status !== 'duplicate')}>Commit reviewed records</Button></Card>}</div>
}
