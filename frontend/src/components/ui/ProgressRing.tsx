export function ProgressRing({ percent, size = 96, label, value }: { percent: number; size?: number; label?: string; value?: string | number }) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg className="h-full w-full -rotate-90" viewBox="0 0 36 36">
        <path
          className="stroke-white/10"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
          fill="none"
          strokeWidth="3"
        />
        <path
          className="stroke-primary"
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
          fill="none"
          strokeDasharray={`${clamped}, 100`}
          strokeLinecap="round"
          strokeWidth="3"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-white">{value ?? `${Math.round(clamped)}%`}</span>
        {label && <span className="text-xs text-white/50">{label}</span>}
      </div>
    </div>
  )
}
