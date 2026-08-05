export function Icon({ name, className = '', filled = false }: { name: string; className?: string; filled?: boolean }) {
  return (
    <span
      className={`msi select-none ${className}`}
      style={{ fontVariationSettings: `'FILL' ${filled ? 1 : 0}` }}
      aria-hidden="true"
    >
      {name}
    </span>
  )
}
