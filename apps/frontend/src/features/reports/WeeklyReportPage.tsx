import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { reportsApi } from '../../lib/api'
import type { WeeklyLearningReport } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'

/** Which of the two actions is in flight, if either. */
type PendingAction = 'snapshot' | 'narration' | null

export function WeeklyReportPage() {
  const { reportId } = useParams()
  const [report, setReport] = useState<WeeklyLearningReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingAction>(null)
  // Kept apart from `error` above, which replaces the whole page: that is the
  // right response to the report failing to load at all, and the wrong one to
  // a button failing. Losing a report the user is reading because a follow-up
  // request timed out would be a worse outcome than the failure itself.
  const [actionError, setActionError] = useState<string | null>(null)
  useEffect(() => { (reportId ? reportsApi.getWeekly(Number(reportId)) : reportsApi.buildWeekly()).then(setReport).catch((e) => setError(e instanceof Error ? e.message : 'Could not build weekly report')) }, [reportId])

  async function run(action: Exclude<PendingAction, null>, request: () => Promise<WeeklyLearningReport>) {
    setPending(action)
    setActionError(null)
    try {
      setReport(await request())
    } catch (e) {
      // Narration goes through an AI provider, which is the likeliest of the
      // two to fail and the one whose failure a user is least able to guess at.
      setActionError(e instanceof Error ? e.message : action === 'narration'
        ? 'Could not generate the AI interpretation.'
        : 'Could not refresh the snapshot.')
    } finally {
      setPending(null)
    }
  }

  if (error) return <p role="alert" className="text-danger">{error}</p>
  if (!report) return <Spinner />
  const snapshot = report.snapshot
  return <div className="mx-auto flex max-w-3xl flex-col gap-6"><div><h1 className="font-display text-3xl font-bold text-white">Weekly learning report</h1><p className="text-white/50">{new Date(snapshot.week.start).toLocaleDateString()} – {new Date(snapshot.week.end).toLocaleDateString()} · {snapshot.week.time_zone}</p></div>{snapshot.data_completeness.warnings.map((warning) => <p key={warning} className="rounded-lg bg-warning/10 p-3 text-sm text-white/80">{warning}</p>)}<div className="grid grid-cols-3 gap-4">{[['Studied', snapshot.studied], ['Retained', snapshot.retained], ['Overdue', snapshot.overdue]].map(([label, value]) => <Card key={String(label)} className="p-5 text-center"><p className="text-3xl font-bold text-primary">{value}</p><p className="text-sm text-white/50">{label}</p></Card>)}</div><ReportList title="Difficult topics" entries={snapshot.difficult_topics} /><ReportList title="Productive time windows" entries={snapshot.productive_time_windows} /><Card className="p-5"><p className="font-display text-lg font-bold text-white">Data source</p><p className="mt-1 text-sm text-white/60">{snapshot.source_range.attempt_count} review attempts across {snapshot.source_range.session_count} sessions. This snapshot is preserved for reproducibility.</p></Card>{report.narration && <Card className="p-5"><p className="font-display text-lg font-bold text-white">AI interpretation</p><p className="mt-2 text-white/70">{report.narration}</p></Card>}<div className="flex flex-col gap-3"><div className="flex gap-3">
    <Button
      variant="secondary"
      loading={pending === 'snapshot'}
      // Both are disabled while either runs: they both replace the whole
      // report, so letting them race would leave whichever finished last
      // silently winning.
      disabled={pending !== null}
      onClick={() => void run('snapshot', () => reportsApi.buildWeekly())}
    >Refresh factual snapshot</Button>
    <Button
      variant="secondary"
      loading={pending === 'narration'}
      disabled={pending !== null}
      onClick={() => void run('narration', () => reportsApi.generateNarration(report.id))}
    >Generate AI interpretation</Button>
  </div>{actionError && <p role="alert" className="text-sm text-danger">{actionError}</p>}</div></div>
}

function ReportList({ title, entries }: { title: string; entries: Array<{ name?: string; label?: string; mistakes?: number; attempts?: number }> }) { return <Card className="p-5"><p className="font-display text-lg font-bold text-white">{title}</p>{entries.length ? <ul className="mt-3 space-y-2 text-sm text-white/70">{entries.map((entry) => <li key={entry.name ?? entry.label}>{entry.name ?? entry.label} — {entry.mistakes ?? entry.attempts}</li>)}</ul> : <p className="mt-2 text-sm text-white/50">Not enough activity this week.</p>}</Card> }
