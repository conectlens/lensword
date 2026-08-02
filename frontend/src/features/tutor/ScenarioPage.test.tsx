import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ScenarioPage } from './ScenarioPage'
import { conversationsApi, groupsApi, scenariosApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  scenariosApi: { list: vi.fn(), start: vi.fn(), finish: vi.fn(), vocabulary: vi.fn() },
  conversationsApi: { send: vi.fn() },
  groupsApi: { list: vi.fn() },
}))

const listScenarios = vi.mocked(scenariosApi.list)
const startAttempt = vi.mocked(scenariosApi.start)
const finishAttempt = vi.mocked(scenariosApi.finish)
const groups = vi.mocked(groupsApi.list)

const RESTAURANT = {
  key: 'restaurant',
  title: 'Ordering at a restaurant',
  briefing: 'You are eating out.',
  goals: ['Order food and drink', 'Ask for the bill'],
  suggested_topics: ['food'],
}

const attempt = (over = {}) => ({
  id: 1,
  session_id: 9,
  scenario: RESTAURANT,
  started_at: '2026-08-02T09:00:00',
  finished_at: null as string | null,
  evaluation: null,
  ...over,
})

beforeEach(() => {
  listScenarios.mockReset()
  startAttempt.mockReset()
  finishAttempt.mockReset()
  groups.mockReset()
  listScenarios.mockResolvedValue([RESTAURANT])
  groups.mockResolvedValue([
    { id: 1, name: 'Spanish', target_language: 'Spanish', word_count: 0, due_count: 0, mastered_count: 0 },
  ] as never)
  startAttempt.mockResolvedValue(attempt())
  // The briefing now carries a vocabulary panel (#144); it must not fail
  // the tests that are about the conversation itself.
  vi.mocked(scenariosApi.vocabulary).mockResolvedValue({
    scenario_key: 'restaurant',
    on_topic: [],
    related: [],
    sparse: true,
    detail: '',
  })
})

async function begin() {
  render(<ScenarioPage />)
  await screen.findByText('Ordering at a restaurant')
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  return screen.findByLabelText('Your message')
}

describe('ScenarioPage', () => {
  it('shows what each scenario asks you to do before you start', async () => {
    render(<ScenarioPage />)

    expect(await screen.findByText('• Order food and drink')).toBeInTheDocument()
  })

  it('keeps the tasks on screen during the conversation', async () => {
    // A role-play whose tasks you have to remember is a memory test wearing a
    // conversation's clothes.
    await begin()

    expect(screen.getByText('• Ask for the bill')).toBeInTheDocument()
  })

  it('says an attempt was not scored rather than showing a zero', async () => {
    // A confident number derived from three messages is exactly what a learner
    // believes because it looks precise.
    finishAttempt.mockResolvedValue(
      attempt({
        finished_at: '2026-08-02T09:10:00',
        evaluation: {
          scored: false,
          scores: [],
          summary: '',
          goals_met: [],
          detail: 'Not enough to judge yet — say at least 4 things and finish again.',
          overall: null,
        },
      }),
    )

    await begin()
    fireEvent.click(screen.getByRole('button', { name: 'Finish and score' }))

    expect(await screen.findByText('Not scored')).toBeInTheDocument()
    expect(screen.getByText(/at least 4 things/)).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('shows the scores and which tasks were met', async () => {
    finishAttempt.mockResolvedValue(
      attempt({
        finished_at: '2026-08-02T09:10:00',
        evaluation: {
          scored: true,
          scores: [{ dimension: 'vocabulary', score: 70, comment: 'good range' }],
          summary: 'Solid attempt.',
          goals_met: ['Order food and drink'],
          detail: '',
          overall: 70,
        },
      }),
    )

    await begin()
    fireEvent.click(screen.getByRole('button', { name: 'Finish and score' }))

    expect(await screen.findByText('How it went')).toBeInTheDocument()
    expect(screen.getByText('Vocabulary')).toBeInTheDocument()
    expect(screen.getByText('✓ Order food and drink')).toBeInTheDocument()
    expect(screen.getByText('○ Ask for the bill')).toBeInTheDocument()
  })

  it('hides the message box once the attempt is finished', async () => {
    finishAttempt.mockResolvedValue(
      attempt({
        finished_at: '2026-08-02T09:10:00',
        evaluation: { scored: true, scores: [], summary: '', goals_met: [], detail: '', overall: null },
      }),
    )

    await begin()
    fireEvent.click(screen.getByRole('button', { name: 'Finish and score' }))

    await waitFor(() => expect(screen.queryByLabelText('Your message')).not.toBeInTheDocument())
  })

  it('will not send an empty message', async () => {
    await begin()

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(conversationsApi.send).not.toHaveBeenCalled()
  })
})
