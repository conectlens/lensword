import type { HTMLAttributes, ReactNode } from 'react'

export function Card({ children, className = '', ...rest }: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={`rounded-lg bg-surface shadow-soft ${className}`} {...rest}>
      {children}
    </div>
  )
}
