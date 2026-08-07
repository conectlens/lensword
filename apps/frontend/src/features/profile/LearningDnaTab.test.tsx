import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { LearningDnaTab } from './LearningDnaTab'
import { learningDnaApi } from '../../lib/api'
import type { EfficacyEstimate } from '../../lib/types'

vi.mock('../../lib/api', () => ({
  learningDnaApi: {
    efficacy: vi.fn(),
    modalityPreference: vi.fn(),
    setModalityPreference: vi.fn(),
  },
}))

const efficacy = vi.mocked(learningDnaApi.efficacy)
const modalityPreference = vi.mocked(learningDnaApi.modalityPreference)
const setModalityPreference = vi.mocked(learningDnaApi.setModalityPreference)

function estimate(overrides: Partial<EfficacyEstimate> = {}): EfficacyEstimate {
  return {
    intervention_type: 'contrast',
    context: {
      item_class: 'reversible_verbs',
      language: 'Spanish',
      prompt_direction: 'production',
      difficulty: 'B1',
      modality: 'text',
      horizon_days: 7,
    },
    status: 'MEASURED',
    intervention_samples: 5,
    control_samples: 5,
    intervention_rate: 0.9,
    control_rate: 0.4,
    effect: 0.5,
    interval_low: 0.1,
    interval_high: 0.9,
    reason: null,
    recommendation: 'contrast has a measured delayed-recall effect of +50.0%...',
    period_start: '2026-01-01T00:00:00Z',
    period_end: '2026-01-10T00:00:00Z',
    valid_until: '2026-02-24T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  efficacy.mockReset()
  modalityPreference.mockReset()
  setModalityPreference.mockReset()
})

describe('LearningDnaTab', () => {
  it('always shows the not-a-medical-assessment disclaimer', async () => {
    efficacy.mockResolvedValue([])
    modalityPreference.mockResolvedValue(null)

    render(<LearningDnaTab />)

    expect(await screen.findByText(/Not a medical or cognitive assessment/)).toBeInTheDocument()
  })

  it('splits estimates into works well / works poorly / not enough evidence', async () => {
    efficacy.mockResolvedValue([
      estimate({ intervention_type: 'contrast', effect: 0.5, status: 'MEASURED' }),
      estimate({ intervention_type: 'isolate', effect: -0.3, status: 'MEASURED' }),
      estimate({ intervention_type: 'mnemonic_replacement', status: 'INSUFFICIENT_EVIDENCE', effect: null, recommendation: null }),
    ])
    modalityPreference.mockResolvedValue(null)

    render(<LearningDnaTab />)

    await waitFor(() => expect(screen.getByText('Works well for you')).toBeInTheDocument())
    // One card per group, identifiable by its intervention type label.
    expect(screen.getByText('contrast')).toBeInTheDocument()
    expect(screen.getByText('isolate')).toBeInTheDocument()
    expect(screen.getByText('mnemonic replacement')).toBeInTheDocument()
  })

  it('never renders a bare percentage without sample size', async () => {
    efficacy.mockResolvedValue([estimate()])
    modalityPreference.mockResolvedValue(null)

    render(<LearningDnaTab />)

    expect(await screen.findByText(/5× intervention · 5× control/)).toBeInTheDocument()
  })

  it('shows the stated preference separately from measured estimates', async () => {
    efficacy.mockResolvedValue([estimate({ context: { ...estimate().context, modality: 'image' }, effect: -0.1 })])
    modalityPreference.mockResolvedValue({ modality: 'image', stated_at: '2026-01-01T00:00:00Z' })

    render(<LearningDnaTab />)

    expect(await screen.findByText('image', { selector: 'span.font-semibold' })).toBeInTheDocument()
    // The measured card for that same modality is in "works poorly", not
    // upgraded by the stated preference above it.
    expect(screen.getByText('Works poorly for you')).toBeInTheDocument()
  })

  it('lets a learner state a new modality preference', async () => {
    efficacy.mockResolvedValue([])
    modalityPreference.mockResolvedValue(null)
    setModalityPreference.mockResolvedValue({ modality: 'audio', stated_at: '2026-01-01T00:00:00Z' })

    render(<LearningDnaTab />)

    const audioButton = await screen.findByRole('button', { name: 'audio' })
    fireEvent.click(audioButton)

    await waitFor(() => expect(setModalityPreference).toHaveBeenCalledWith('audio'))
  })

  it('lets a learner inspect the underlying numbers', async () => {
    efficacy.mockResolvedValue([estimate()])
    modalityPreference.mockResolvedValue(null)

    render(<LearningDnaTab />)

    const inspectButton = await screen.findByText('Inspect the numbers')
    fireEvent.click(inspectButton)

    expect(await screen.findByText('95% interval')).toBeInTheDocument()
  })

  it('reports a failed load instead of rendering as though nothing was measured', async () => {
    efficacy.mockRejectedValue(new Error('offline'))
    modalityPreference.mockResolvedValue(null)

    render(<LearningDnaTab />)

    await waitFor(() =>
      expect(screen.getByText(/Could not load your Learning DNA/)).toBeInTheDocument(),
    )
  })
})
