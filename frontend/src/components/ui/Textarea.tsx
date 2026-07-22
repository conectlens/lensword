import { forwardRef, type TextareaHTMLAttributes } from 'react'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  hint?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, className = '', id, ...rest }, ref,
) {
  const areaId = id ?? rest.name
  return (
    <label className="flex flex-col gap-2" htmlFor={areaId}>
      {label && <span className="text-sm font-medium text-white">{label}</span>}
      <textarea
        ref={ref}
        id={areaId}
        className={`w-full rounded-lg border border-white/10 bg-white/5 p-3 text-base text-white placeholder:text-white/30 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/40 ${className}`}
        {...rest}
      />
      {hint && <span className="text-xs text-white/40">{hint}</span>}
    </label>
  )
})
