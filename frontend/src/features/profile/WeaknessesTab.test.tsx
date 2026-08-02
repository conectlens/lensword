import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { WeaknessesTab } from './WeaknessesTab'
import { settingsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  settingsApi: { weaknesses: vi.fn() },
}))

const weaknesses = vi.mocked(settingsApi.weaknesses)

const empty = {
  total_mistakes: 0,
  categories: [],
  confused_pairs: [],
  insufficient_data: true,
}

beforeEach(() => {
  weaknesses.mockReset()
})

describe('WeaknessesTab', () => {
  it('says there is not enough evidence rather than showing an empty profile', async () => {
    // The distinction the whole feature rests on: "no weaknesses found" is a
    // claim, and it is not the one we are entitled to make here.
    weaknesses.mockResolvedValue(empty)

    render(<WeaknessesTab />)

    expect(await screen.findByText('Not enough evidence yet')).toBeInTheDocument()
  })

  it('distinguishes no mistakes at all from too few to judge', async () => {
    weaknesses.mockResolvedValue({ ...empty, total_mistakes: 2 })

    render(<WeaknessesTab />)

    expect(await screen.findByText(/2 mistakes recorded so far/)).toBeInTheDocument()
  })

  it('shows the count next to every percentage', async () => {
    // 60% of five mistakes and 60% of five hundred are different claims.
    weaknesses.mockResolvedValue({
      total_mistakes: 5,
      categories: [{ category: 'spelling', occurrences: 3, share: 0.6 }],
      confused_pairs: [],
      insufficient_data: false,
    })

    render(<WeaknessesTab />)

    expect(await screen.findByText('3× · 60%')).toBeInTheDocument()
  })

  it('names a deleted word rather than leaving a gap', async () => {
    weaknesses.mockResolvedValue({
      total_mistakes: 4,
      categories: [],
      confused_pairs: [
        {
          word_id: 1,
          word_term: 'gato',
          confused_with_word_id: 2,
          confused_with_term: null,
          occurrences: 2,
        },
      ],
      insufficient_data: false,
    })

    render(<WeaknessesTab />)

    expect(await screen.findByText(/a deleted word/)).toBeInTheDocument()
  })

  it('reports a failed load instead of rendering as though there were no mistakes', async () => {
    weaknesses.mockRejectedValue(new Error('offline'))

    render(<WeaknessesTab />)

    await waitFor(() =>
      expect(screen.getByText(/Could not load your weakness profile/)).toBeInTheDocument(),
    )
  })
})
