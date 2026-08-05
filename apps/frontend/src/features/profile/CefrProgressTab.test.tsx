import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { CefrProgressTab } from './CefrProgressTab'
import { settingsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  settingsApi: { cefrProgress: vi.fn() },
}))

const cefrProgress = vi.mocked(settingsApi.cefrProgress)

const level = (name: string, total = 0, started = 0, mastered = 0) => ({
  level: name,
  total,
  started,
  mastered,
  mastery_share: total ? mastered / total : 0,
})

const SIX = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'].map((n) => level(n))

beforeEach(() => {
  cefrProgress.mockReset()
})

describe('CefrProgressTab', () => {
  it('never claims an overall level', async () => {
    // The number everyone wants and the one this data cannot support: someone
    // who added forty C1 words yesterday is not C1.
    cefrProgress.mockResolvedValue({
      levels: [level('A1', 10, 10, 10), ...SIX.slice(1)],
      unlevelled: null,
      total_words: 10,
    })

    render(<CefrProgressTab />)

    await screen.findByText('A1')
    expect(screen.queryByText(/you are|your level is|current level/i)).not.toBeInTheDocument()
  })

  it('shows every level, including the empty ones', async () => {
    // A gap in the axis reads as "no data collected"; a zero reads as "nothing
    // here yet", and the second is the true one.
    cefrProgress.mockResolvedValue({
      levels: [level('A1', 3, 3, 1), ...SIX.slice(1)],
      unlevelled: null,
      total_words: 3,
    })

    render(<CefrProgressTab />)

    expect(await screen.findByText('C2')).toBeInTheDocument()
    expect(screen.getAllByText('No words yet').length).toBe(5)
  })

  it('gives unlevelled words their own row rather than hiding them', async () => {
    cefrProgress.mockResolvedValue({
      levels: SIX,
      unlevelled: level('unknown', 7, 2, 1),
      total_words: 7,
    })

    render(<CefrProgressTab />)

    expect(await screen.findByText('No level recorded')).toBeInTheDocument()
  })

  it('reports mastery as a count as well as a percentage', async () => {
    cefrProgress.mockResolvedValue({
      levels: [level('A1', 4, 4, 1), ...SIX.slice(1)],
      unlevelled: null,
      total_words: 4,
    })

    render(<CefrProgressTab />)

    expect(await screen.findByText('1/4 mastered · 25%')).toBeInTheDocument()
  })

  it('says there are no words rather than rendering six empty bars', async () => {
    cefrProgress.mockResolvedValue({ levels: SIX, unlevelled: null, total_words: 0 })

    render(<CefrProgressTab />)

    expect(await screen.findByText('No words yet')).toBeInTheDocument()
    expect(screen.queryByText('C2')).not.toBeInTheDocument()
  })

  it('reports a failed load instead of rendering as though there were no words', async () => {
    cefrProgress.mockRejectedValue(new Error('offline'))

    render(<CefrProgressTab />)

    expect(await screen.findByText(/Could not load your level progress/)).toBeInTheDocument()
  })
})
