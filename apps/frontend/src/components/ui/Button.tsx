import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const variantClasses: Record<Variant, string> = {
  primary: 'bg-primary text-ink font-semibold hover:brightness-95 shadow-soft',
  secondary: 'bg-white/10 text-white hover:bg-white/20',
  ghost: 'bg-transparent text-white/80 hover:bg-white/10 hover:text-white',
  danger: 'bg-danger/90 text-white hover:bg-danger',
}

const sizeClasses: Record<Size, string> = {
  sm: 'h-9 px-4 text-sm',
  md: 'h-11 px-6 text-sm',
  lg: 'h-12 px-6 text-base',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: string
  loading?: boolean
  children?: ReactNode
}

export function Button({ variant = 'primary', size = 'md', icon, loading, children, className = '', disabled, ...rest }: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg tracking-wide transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? (
        <span className="msi animate-spin text-base leading-none">progress_activity</span>
      ) : icon ? (
        <span className="msi text-base leading-none">{icon}</span>
      ) : null}
      {children}
    </button>
  )
}
