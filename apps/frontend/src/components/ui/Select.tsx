import { forwardRef, type SelectHTMLAttributes } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  options: { value: string; label: string }[]
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, options, className = '', id, ...rest }, ref,
) {
  const selectId = id ?? rest.name
  return (
    <label className="flex flex-col gap-2" htmlFor={selectId}>
      {label && <span className="text-sm font-medium text-white">{label}</span>}
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          className={`h-12 w-full appearance-none rounded-lg border border-white/10 bg-white/5 px-4 pr-10 text-base text-white focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/40 ${className}`}
          {...rest}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-surface text-white">
              {opt.label}
            </option>
          ))}
        </select>
        <span className="msi pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-white/40">expand_more</span>
      </div>
    </label>
  )
})
