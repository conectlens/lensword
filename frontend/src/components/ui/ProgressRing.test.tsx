import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProgressRing } from './ProgressRing'

describe('ProgressRing', () => {
  it('shows the rounded percent by default', () => {
    render(<ProgressRing percent={82.6} />)
    expect(screen.getByText('83%')).toBeInTheDocument()
  })

  it('shows a custom value when provided instead of the percent', () => {
    render(<ProgressRing percent={50} value={15} label="Words" />)
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByText('Words')).toBeInTheDocument()
  })

  it('clamps out-of-range percentages into the dash array', () => {
    const { container } = render(<ProgressRing percent={150} />)
    const primaryArc = container.querySelector('.stroke-primary')
    expect(primaryArc).toHaveAttribute('stroke-dasharray', '100, 100')
  })
})
