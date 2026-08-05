import type { WordStatus } from '../../lib/types'

const CONFIG: Record<WordStatus, { label: string; className: string }> = {
  new: { label: 'New', className: 'bg-white/10 text-white/70' },
  learning: { label: 'Learning', className: 'bg-yellow-500/20 text-yellow-400' },
  review: { label: 'Review', className: 'bg-blue-500/20 text-blue-400' },
  mastered: { label: 'Mastered', className: 'bg-green-500/20 text-green-400' },
  needs_review: { label: 'Needs review', className: 'bg-red-500/20 text-red-400' },
}

export function StatusChip({ status }: { status: WordStatus }) {
  const { label, className } = CONFIG[status]
  return <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${className}`}>{label}</span>
}
