import type { ReactNode } from 'react'
import { Icon } from './Icon'

export function EmptyState({ icon, title, description, action }: { icon: string; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-lg border-2 border-dashed border-white/15 px-6 py-16 text-center">
      <Icon name={icon} className="text-5xl text-white/30" />
      <div className="flex max-w-sm flex-col gap-1">
        <p className="font-display text-xl font-bold text-white">{title}</p>
        <p className="text-white/50">{description}</p>
      </div>
      {action}
    </div>
  )
}
