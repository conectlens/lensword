import { Icon } from './Icon'

export function Spinner({ className = 'text-2xl text-primary' }: { className?: string }) {
  return (
    <div className="flex w-full items-center justify-center py-16">
      <Icon name="progress_activity" className={`animate-spin ${className}`} />
    </div>
  )
}
