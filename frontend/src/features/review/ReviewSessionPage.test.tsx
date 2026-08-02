import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ReviewSessionPage } from './ReviewSessionPage'
import { reviewApi, ApiRequestError } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    reviewApi: { start: vi.fn(), submitAnswer: vi.fn(), complete: vi.fn() },
  }
})

const start = vi.mocked(reviewApi.start)

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ReviewSessionPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  start.mockReset()
})

describe('ReviewSessionPage empty states', () => {
  it('tells a mistakes session there is nothing to relearn, not that nothing is due', async () => {
    // "Nothing due" is about the scheduler. Someone who has just cleared every
    // mistake would be told the wrong thing entirely.
    start.mockRejectedValue(new ApiRequestError(409, 'no words'))

    renderAt('/review?mode=mistakes')

    expect(await screen.findByText('No mistakes to review')).toBeInTheDocument()
  })

  it('still says nothing is due for an ordinary session', async () => {
    start.mockRejectedValue(new ApiRequestError(409, 'no words'))

    renderAt('/review?mode=standard')

    expect(await screen.findByText('Nothing due right now')).toBeInTheDocument()
  })

  it('asks the backend for the mistakes mode when that is the route', async () => {
    start.mockRejectedValue(new ApiRequestError(409, 'no words'))

    renderAt('/review?mode=mistakes')

    await screen.findByText('No mistakes to review')
    expect(start).toHaveBeenCalledWith('mistakes', null, 20)
  })
})
