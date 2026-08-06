import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ReviewSessionPage } from './ReviewSessionPage'
import { reviewApi, ApiRequestError } from '../../lib/api'
import { queueLength, loadQueuedOperations } from '../../lib/offlineQueue'
import type { Word } from '../../lib/types'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    reviewApi: { start: vi.fn(), submitAnswer: vi.fn(), answer: vi.fn(), complete: vi.fn() },
  }
})

const start = vi.mocked(reviewApi.start)
const answer = vi.mocked(reviewApi.answer)

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ReviewSessionPage />
    </MemoryRouter>,
  )
}

function reviewWord(overrides: Partial<Word> = {}): Word {
  return {
    id: 1,
    group_id: 1,
    term: 'Correr',
    target_language: 'Spanish',
    translations: ['to run'],
    example_sentence: null,
    mnemonic: null,
    category: null,
    definition: null,
    part_of_speech: null,
    cefr_level: null,
    pronunciation: null,
    collocations: [],
    tags: [],
    ai_confidence: null,
    ai_provider: null,
    ai_model: null,
    ai_verified_at: null,
    ai_state: 'unverified',
    synonyms: [],
    antonyms: [],
    topics: [],
    review_state: {
      strength: 0, ease_factor: 2.5, interval_days: 0, repetitions: 0,
      due_at: '2026-08-06T09:00:00Z', last_reviewed_at: null, status: 'new',
    },
    created_at: '2026-08-01T00:00:00Z',
    revision: 1,
    ...overrides,
  }
}

beforeEach(() => {
  start.mockReset()
  answer.mockReset()
  localStorage.clear()
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

describe('ReviewSessionPage offline (issue #218)', () => {
  it('queues an answer that fails on a network error and still advances the session', async () => {
    const word = reviewWord()
    start.mockResolvedValue({ session_id: 7, mode: 'standard', words: [word] })
    answer.mockRejectedValue(new TypeError('Failed to fetch'))

    renderAt('/review?mode=standard')

    const input = await screen.findByPlaceholderText('Your answer...')
    fireEvent.change(input, { target: { value: 'to run' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))

    await waitFor(() => expect(answer).toHaveBeenCalledWith(7, 1, 'correct'))
    expect(screen.getByText('Correct!')).toBeInTheDocument()

    const queued = loadQueuedOperations()
    expect(queueLength()).toBe(1)
    expect(queued[0]).toMatchObject({
      entity_type: 'review',
      entity_id: null,
      operation: 'append',
      payload: { session_id: 7, word_id: 1, outcome: 'correct' },
      base_revision: null,
    })
  })
})
