import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ObservationHistoryTab } from './ObservationHistoryTab'
import { observationsApi } from '../../lib/api'
import type { ObservationHistoryItem } from '../../lib/types'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    observationsApi: { history: vi.fn(), correct: vi.fn() },
  }
})

const history = vi.mocked(observationsApi.history)
const correct = vi.mocked(observationsApi.correct)

function makeItem(overrides: Partial<ObservationHistoryItem> = {}): ObservationHistoryItem {
  return {
    observation_id: 'obs-1',
    word_id: 1,
    word_term: 'Correr',
    outcome: 'incorrect',
    session_mode: 'standard',
    observed_at: '2026-08-06T09:00:00Z',
    attempted_answer: 'Corriendo',
    modality: 'typing',
    hint_used: false,
    correction: null,
    ...overrides,
  }
}

beforeEach(() => {
  history.mockReset()
  correct.mockReset()
})

describe('ObservationHistoryTab', () => {
  it('shows an empty state when nothing has been recorded', async () => {
    history.mockResolvedValue({ items: [], has_more: false })

    render(<ObservationHistoryTab />)

    expect(await screen.findByText('Nothing recorded yet')).toBeInTheDocument()
  })

  it('lists a recorded observation with its word and outcome', async () => {
    history.mockResolvedValue({ items: [makeItem()], has_more: false })

    render(<ObservationHistoryTab />)

    expect(await screen.findByText('Correr')).toBeInTheDocument()
    expect(screen.getByText(/Incorrect/)).toBeInTheDocument()
  })

  it('shows a deleted word rather than leaving a gap', async () => {
    history.mockResolvedValue({ items: [makeItem({ word_term: null })], has_more: false })

    render(<ObservationHistoryTab />)

    expect(await screen.findByText('a deleted word')).toBeInTheDocument()
  })

  it('flagging an observation as misgraded shows the flag and hides the action', async () => {
    history.mockResolvedValue({ items: [makeItem()], has_more: false })
    correct.mockResolvedValue({
      correction_id: 'corr-1', reason: 'misgraded', note: null, created_at: '2026-08-06T10:00:00Z',
    })

    render(<ObservationHistoryTab />)
    await screen.findByText('Correr')

    fireEvent.click(screen.getByRole('button', { name: 'Flag' }))
    fireEvent.click(screen.getByRole('button', { name: 'Misgraded' }))

    expect(await screen.findByText('Flagged: Misgraded')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Flag' })).not.toBeInTheDocument()
    expect(correct).toHaveBeenCalledWith('obs-1', 'misgraded', '')
  })

  it('an already-flagged observation shows the flag badge instead of a Flag button', async () => {
    history.mockResolvedValue({
      items: [
        makeItem({
          correction: { correction_id: 'corr-1', reason: 'irrelevant', note: null, created_at: '2026-08-06T10:00:00Z' },
        }),
      ],
      has_more: false,
    })

    render(<ObservationHistoryTab />)

    expect(await screen.findByText('Flagged: Irrelevant')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Flag' })).not.toBeInTheDocument()
  })

  it('loads the next page and appends it to the list', async () => {
    history.mockResolvedValueOnce({ items: [makeItem({ observation_id: 'obs-1' })], has_more: true })
    history.mockResolvedValueOnce({
      items: [makeItem({ observation_id: 'obs-2', word_term: 'Saltar' })],
      has_more: false,
    })

    render(<ObservationHistoryTab />)
    await screen.findByText('Correr')

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

    expect(await screen.findByText('Saltar')).toBeInTheDocument()
    expect(screen.getByText('Correr')).toBeInTheDocument()
    expect(history).toHaveBeenLastCalledWith(20, 1)
  })

  it('reports a failed load instead of rendering as though there were no observations', async () => {
    history.mockRejectedValue(new Error('offline'))

    render(<ObservationHistoryTab />)

    await waitFor(() =>
      expect(screen.getByText(/Could not load your review history/)).toBeInTheDocument(),
    )
  })
})
