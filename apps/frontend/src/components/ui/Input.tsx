import { forwardRef, type InputHTMLAttributes } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, className = '', id, ...rest }, ref,
) {
  const inputId = id ?? rest.name
  return (
    <label className="flex flex-col gap-2" htmlFor={inputId}>
      {label && <span className="text-sm font-medium text-white">{label}</span>}
      <input
        ref={ref}
        id={inputId}
        className={`h-12 w-full rounded-lg border border-white/10 bg-white/5 px-4 text-base text-white placeholder:text-white/30 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/40 ${className}`}
        {...rest}
      />
      {error && <span className="text-xs text-danger">{error}</span>}
    </label>
  )
})
