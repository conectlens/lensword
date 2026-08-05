import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { AiProvenancePanel, AiStateBadge } from './AiProvenance'
import { wordsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  wordsApi: { history: vi.fn(), verify: vi.fn(), unverify: vi.fn() },
}))

const history = vi.mocked(wordsApi.history)
const verify = vi.mocked(wordsApi.verify)
const unverify = vi.mocked(wordsApi.unverify)

beforeEach(() => {
  history.mockReset()
  verify.mockReset()
  unverify.mockReset()
  history.mockResolvedValue([])
})

describe('AiStateBadge', () => {
  it('shows no badge on a card nobody claimed a model wrote', () => {
    // "Unverified" on something a person typed would invite them to verify
    // their own writing, which means nothing.
    const { container } = render(<AiStateBadge state="human" />)

    expect(container).toBeEmptyDOMElement()
  })

  it('distinguishes checked from unchecked model cards', () => {
    const { rerender } = render(<AiStateBadge state="unverified" />)
    expect(screen.getByText(/unchecked/)).toBeInTheDocument()

    rerender(<AiStateBadge state="verified" />)
    expect(screen.getByText(/verified/)).toBeInTheDocument()
  })
})

describe('AiProvenancePanel', () => {
  it('offers no verify control on a hand-written card', () => {
    render(<AiProvenancePanel wordId={1} state="human" onStateChange={vi.fn()} />)

    expect(screen.queryByRole('button', { name: /verified/i })).not.toBeInTheDocument()
  })

  it('marks an unverified model card as verified', async () => {
    verify.mockResolvedValue({ word_id: 1, state: 'verified', ai_verified_at: '2026-08-02T09:00:00' })
    const onStateChange = vi.fn()

    render(<AiProvenancePanel wordId={1} state="unverified" onStateChange={onStateChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mark as verified' }))

    await waitFor(() => expect(onStateChange).toHaveBeenCalledWith('verified'))
  })

  it('lets verification be withdrawn', async () => {
    // Someone who realises they approved a card too quickly needs a way to say
    // so.
    unverify.mockResolvedValue({ word_id: 1, state: 'unverified', ai_verified_at: null })
    const onStateChange = vi.fn()

    render(<AiProvenancePanel wordId={1} state="verified" onStateChange={onStateChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw verification' }))

    await waitFor(() => expect(onStateChange).toHaveBeenCalledWith('unverified'))
  })

  it('says a first value was added rather than showing a blank before', async () => {
    // "Added" and "replaced" are different facts.
    history.mockResolvedValue([
      {
        field: 'definition',
        before_value: null,
        after_value: 'a small cat',
        source: 'ai',
        changed_at: '2026-08-02T09:00:00',
      },
    ])

    render(<AiProvenancePanel wordId={1} state="unverified" onStateChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show history' }))

    expect(await screen.findByText('added')).toBeInTheDocument()
  })

  it('names a bulk edit distinctly from an ordinary one', async () => {
    // "I set the level on forty cards" is a different degree of attention from
    // "I changed this card".
    history.mockResolvedValue([
      {
        field: 'cefr_level',
        before_value: 'A1',
        after_value: 'B1',
        source: 'bulk',
        changed_at: '2026-08-02T09:00:00',
      },
    ])

    render(<AiProvenancePanel wordId={1} state="unverified" onStateChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show history' }))

    expect(await screen.findByText(/in a bulk edit/)).toBeInTheDocument()
  })

  it('says nothing has changed rather than showing an empty list', async () => {
    render(<AiProvenancePanel wordId={1} state="unverified" onStateChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show history' }))

    expect(await screen.findByText(/Nothing has changed on this card/)).toBeInTheDocument()
  })
})
