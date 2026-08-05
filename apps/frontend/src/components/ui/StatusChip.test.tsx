import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusChip } from './StatusChip'

describe('StatusChip', () => {
  it('renders the human label for each word status', () => {
    render(<StatusChip status="mastered" />)
    expect(screen.getByText('Mastered')).toBeInTheDocument()
  })

  it('renders needs_review as "Needs review"', () => {
    render(<StatusChip status="needs_review" />)
    expect(screen.getByText('Needs review')).toBeInTheDocument()
  })
})
