import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { LearningPathsPage } from './LearningPathsPage'
import { groupsApi, learningPathsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  learningPathsApi: { list: vi.fn(), generate: vi.fn(), remove: vi.fn() },
  groupsApi: { list: vi.fn() },
}))

const list = vi.mocked(learningPathsApi.list)
const generate = vi.mocked(learningPathsApi.generate)
const groups = vi.mocked(groupsApi.list)

const milestone = (over = {}) => ({
  position: 0,
  title: 'Greetings',
  description: 'Say hello',
  topic: 'greetings',
  target_word_count: 5,
  cefr_level: 'A1',
  words_held: 2,
  words_mastered: 1,
  complete: false,
  share: 0.4,
  ...over,
})

const path = (over = {}) => ({
  id: 1,
  goal: 'Order food in Spain',
  target_language: 'Spanish',
  group_id: null,
  ai_provider: 'ollama',
  ai_model: 'llama3.2',
  created_at: '2026-08-02T09:00:00',
  milestones: [milestone()],
  completed_count: 0,
  share: 0,
  next_milestone: milestone(),
  ...over,
})

beforeEach(() => {
  list.mockReset()
  generate.mockReset()
  groups.mockReset()
  list.mockResolvedValue([])
  groups.mockResolvedValue([
    { id: 1, name: 'Spanish', target_language: 'Spanish', word_count: 0, due_count: 0, mastered_count: 0 },
  ] as never)
})

describe('LearningPathsPage', () => {
  it('shows measured counts rather than a bare percentage', async () => {
    // Held and mastered are different claims; reporting only the first would
    // overstate what the learner can actually do.
    list.mockResolvedValue([path()])

    render(<LearningPathsPage />)

    expect(await screen.findByText(/2\/5 words/)).toBeInTheDocument()
    expect(screen.getByText(/1 mastered/)).toBeInTheDocument()
  })

  it('names the next milestone rather than leaving it to be found', async () => {
    list.mockResolvedValue([path()])

    render(<LearningPathsPage />)

    expect(await screen.findByText('Next: Greetings')).toBeInTheDocument()
  })

  it('says when every milestone is met', async () => {
    list.mockResolvedValue([
      path({ next_milestone: null, completed_count: 1, milestones: [milestone({ complete: true })] }),
    ])

    render(<LearningPathsPage />)

    expect(await screen.findByText('Every milestone met.')).toBeInTheDocument()
  })

  it('shows the server wording when AI is switched off', async () => {
    // "Not configured" and "temporarily down" need different responses from
    // the learner, and rewriting the message here would lose that.
    generate.mockResolvedValue({
      status: 'disabled',
      path: null,
      detail: 'AI is not configured for this deployment, so paths cannot be generated.',
    })

    render(<LearningPathsPage />)
    await screen.findByLabelText('Your goal')
    fireEvent.change(screen.getByLabelText('Your goal'), { target: { value: 'Order food' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate a path' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('AI is not configured')
  })

  it('reports an unavailable model without discarding the form', async () => {
    generate.mockResolvedValue({ status: 'unavailable', path: null, detail: 'model is starting' })

    render(<LearningPathsPage />)
    await screen.findByLabelText('Your goal')
    fireEvent.change(screen.getByLabelText('Your goal'), { target: { value: 'Order food' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate a path' }))

    await screen.findByRole('alert')
    expect(screen.getByLabelText('Your goal')).toHaveValue('Order food')
  })

  it('will not generate from an empty goal', async () => {
    render(<LearningPathsPage />)
    await screen.findByLabelText('Your goal')

    expect(screen.getByRole('button', { name: 'Generate a path' })).toBeDisabled()
    expect(generate).not.toHaveBeenCalled()
  })

  it('adds a generated path to the list', async () => {
    generate.mockResolvedValue({ status: 'ok', path: path({ goal: 'Ride the metro' }), detail: null })

    render(<LearningPathsPage />)
    await screen.findByLabelText('Your goal')
    fireEvent.change(screen.getByLabelText('Your goal'), { target: { value: 'Ride the metro' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate a path' }))

    await waitFor(() => expect(screen.getByText('Ride the metro')).toBeInTheDocument())
  })

  it('invites a goal rather than showing an empty page', async () => {
    render(<LearningPathsPage />)

    expect(await screen.findByText(/Describe a goal above/)).toBeInTheDocument()
  })
})
