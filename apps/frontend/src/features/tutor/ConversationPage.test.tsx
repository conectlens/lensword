import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { ConversationPage } from './ConversationPage'
import { conversationsApi, groupsApi } from '../../lib/api'
import { selectOption } from '../../test/selectOption'

vi.mock('../../lib/api', () => ({
  conversationsApi: { start: vi.fn(), send: vi.fn() },
  groupsApi: { list: vi.fn() },
}))

const start = vi.mocked(conversationsApi.start)
const send = vi.mocked(conversationsApi.send)
const groups = vi.mocked(groupsApi.list)

const conversation = (over = {}) => ({
  id: 1,
  target_language: 'Spanish',
  difficulty: 'steady',
  scenario: null,
  group_id: null,
  created_at: '2026-08-02T09:00:00',
  ended_at: null,
  messages: [],
  ...over,
})

const message = (over = {}) => ({
  id: 1,
  speaker: 'learner' as const,
  text: 'yo tiene un gato',
  corrections: [],
  created_at: '2026-08-02T09:00:00',
  ...over,
})

beforeEach(() => {
  start.mockReset()
  send.mockReset()
  groups.mockReset()
  groups.mockResolvedValue([
    { id: 1, name: 'Spanish', target_language: 'Spanish', word_count: 0, due_count: 0, mastered_count: 0 },
  ] as never)
  start.mockResolvedValue(conversation())
})

async function begin() {
  render(<ConversationPage />)
  await screen.findByLabelText('Conversation language')
  fireEvent.click(screen.getByRole('button', { name: 'Start talking' }))
  return screen.findByLabelText('Your message')
}

describe('ConversationPage', () => {
  it('keeps what the learner typed when the tutor cannot reply', async () => {
    // The server stores the turn before calling the model, and losing it on
    // screen would undo that.
    send.mockResolvedValue({
      status: 'unavailable',
      learner_message: message(),
      tutor_message: null,
      detail: 'model is starting',
    })

    const input = await begin()
    fireEvent.change(input, { target: { value: 'yo tiene un gato' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('yo tiene un gato')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('model is starting')
  })

  it('shows the learner their own words beside the correction', async () => {
    // Showing only the corrected form hides what they actually wrote, which is
    // the thing they need to see.
    send.mockResolvedValue({
      status: 'ok',
      learner_message: message(),
      tutor_message: message({
        id: 2,
        speaker: 'tutor',
        text: 'Casi.',
        corrections: [
          { original: 'yo tiene', corrected: 'yo tengo', explanation: 'first person' },
        ],
      }),
      detail: null,
    })

    const input = await begin()
    fireEvent.change(input, { target: { value: 'yo tiene un gato' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('yo tiene')).toBeInTheDocument()
    expect(screen.getByText('yo tengo')).toBeInTheDocument()
    expect(screen.getByText('first person')).toBeInTheDocument()
  })

  it('clears the box only once the message was accepted', async () => {
    send.mockResolvedValue({
      status: 'ok',
      learner_message: message(),
      tutor_message: message({ id: 2, speaker: 'tutor', text: 'Hola' }),
      detail: null,
    })

    const input = await begin()
    fireEvent.change(input, { target: { value: 'yo tiene un gato' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(input).toHaveValue(''))
  })

  it('does not clear the box when the send itself failed', async () => {
    send.mockRejectedValue(new Error('offline'))

    const input = await begin()
    fireEvent.change(input, { target: { value: 'no se envía' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await screen.findByRole('alert')
    expect(input).toHaveValue('no se envía')
  })

  it('will not send an empty message', async () => {
    await begin()

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(send).not.toHaveBeenCalled()
  })

  it('offers named difficulty levels rather than numbers', async () => {
    render(<ConversationPage />)

    // The names now live in the listbox rather than in the closed trigger,
    // so the assertion opens it — which is also what a user must do to see
    // them.
    const trigger = await screen.findByRole('combobox', { name: 'Difficulty' })
    fireEvent.keyDown(trigger, { key: 'Enter' })
    const listbox = await screen.findByRole('listbox')
    expect(within(listbox).getByRole('option', { name: 'Gentle' })).toBeInTheDocument()
    expect(within(listbox).getByRole('option', { name: 'Stretch me' })).toBeInTheDocument()
  })

  it('passes the chosen difficulty when starting', async () => {
    render(<ConversationPage />)
    await screen.findByRole('combobox', { name: 'Difficulty' })
    await selectOption('Difficulty', 'Stretch me')
    fireEvent.click(screen.getByRole('button', { name: 'Start talking' }))

    // Two arguments: the client defaults the scenario, which #136 will use.
    await waitFor(() => expect(start).toHaveBeenCalledWith('Spanish', 'stretch'))
  })
})
