import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { AcquisitionSessionPage } from './AcquisitionSessionPage'
import { acquisitionApi, ApiRequestError } from '../../lib/api'
import type { AcquisitionState, Word } from '../../lib/types'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    acquisitionApi: { due: vi.fn(), word: vi.fn(), answer: vi.fn() },
  }
})

const due = vi.mocked(acquisitionApi.due)
const word = vi.mocked(acquisitionApi.word)
const answer = vi.mocked(acquisitionApi.answer)

function makeState(overrides: Partial<AcquisitionState> = {}): AcquisitionState {
  const now = Date.now()
  return {
    word_id: 1,
    rung: 0,
    ladder_version: 1,
    started_at: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    updated_at: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    due_at: new Date(now - 24 * 60 * 60 * 1000 + 30 * 1000).toISOString(),
    graduated: false,
    entry_reason: 'weak_acquisition_diagnosis',
    // Must stay in the future relative to whenever the test actually runs —
    // 'shows why the word entered the loop and roughly when it hands back
    // to FSRS' asserts the "hands back to spaced repetition in ~Xh" branch
    // of describeHandoff(), which requires estimated_graduation_at > now.
    // A hardcoded absolute timestamp passed while this suite sat unrun and
    // broke every run afterward — this is why it stayed a bare `Date.now()`
    // call rather than a fixed-clock/fake-timers setup other suites use.
    estimated_graduation_at: new Date(now + 24 * 60 * 60 * 1000).toISOString(),
    ...overrides,
  }
}

function makeWord(overrides: Partial<Word> = {}): Word {
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/stabilize']}>
      <AcquisitionSessionPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  due.mockReset()
  word.mockReset()
  answer.mockReset()
})

describe('AcquisitionSessionPage', () => {
  it('shows nothing-to-stabilize when the due list is empty', async () => {
    due.mockResolvedValue([])

    renderPage()

    expect(await screen.findByText('Nothing to stabilize')).toBeInTheDocument()
  })

  it('tells the learner to enable the loop when the account flag is off (403)', async () => {
    due.mockRejectedValue(new ApiRequestError(403, 'disabled'))

    renderPage()

    expect(await screen.findByText('Stabilization unavailable')).toBeInTheDocument()
  })

  it('shows why the word entered the loop and roughly when it hands back to FSRS', async () => {
    due.mockResolvedValue([makeState()])
    word.mockResolvedValue(makeWord())

    renderPage()

    expect(await screen.findByText('Correr')).toBeInTheDocument()
    expect(screen.getByText('Flagged as shaky on your last attempt')).toBeInTheDocument()
    expect(screen.getByText(/hands back to spaced repetition/)).toBeInTheDocument()
  })

  it('does not render a handoff estimate once graduated', async () => {
    due.mockResolvedValue([makeState({ graduated: true, estimated_graduation_at: null, entry_reason: null })])
    word.mockResolvedValue(makeWord())

    renderPage()

    await screen.findByText('Correr')
    expect(screen.queryByText(/hands back to spaced repetition/)).not.toBeInTheDocument()
  })

  it('submits an answer via the "1" keyboard shortcut', async () => {
    due.mockResolvedValue([makeState()])
    word.mockResolvedValue(makeWord())
    answer.mockResolvedValue(null)

    renderPage()
    await screen.findByText('Correr')

    fireEvent.keyDown(window, { key: '1' })

    expect(answer).toHaveBeenCalledWith(1, 'correct')
  })

  it('submits an answer via the "2" keyboard shortcut', async () => {
    due.mockResolvedValue([makeState()])
    word.mockResolvedValue(makeWord())
    answer.mockResolvedValue(makeState())

    renderPage()
    await screen.findByText('Correr')

    fireEvent.keyDown(window, { key: '2' })

    expect(answer).toHaveBeenCalledWith(1, 'incorrect')
  })
})
