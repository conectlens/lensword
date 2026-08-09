import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { CompanionChatPage } from './CompanionChatPage'
import { companionApi, groupsApi, settingsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  companionApi: { start: vi.fn(), chat: vi.fn(), finish: vi.fn() },
  groupsApi: { list: vi.fn() },
  settingsApi: { getRecallSettings: vi.fn() },
}))

const start = vi.mocked(companionApi.start)
const chat = vi.mocked(companionApi.chat)
const groups = vi.mocked(groupsApi.list)
const recallSettings = vi.mocked(settingsApi.getRecallSettings)

const session = (over = {}) => ({
  id: 'sess-1',
  connection_id: 'lensword-app',
  client_id: 'in-app-chat',
  goal: null,
  language: 'Spanish',
  group_id: null,
  difficulty: null,
  active_activity: null,
  summary: null,
  status: 'active' as const,
  revision: 1,
  created_at: '2026-08-10T09:00:00',
  updated_at: '2026-08-10T09:00:00',
  turns: [],
  ...over,
})

const turn = (over = {}) => ({
  id: 1,
  session_id: 'sess-1',
  role: 'user' as const,
  content: 'Hola',
  activity_id: null,
  operation_id: null,
  created_at: '2026-08-10T09:00:00',
  ...over,
})

beforeEach(() => {
  start.mockReset()
  chat.mockReset()
  groups.mockReset()
  recallSettings.mockReset()
  recallSettings.mockResolvedValue({ ai_companion_enabled: true } as never)
  groups.mockResolvedValue([
    { id: 1, name: 'Spanish', target_language: 'Spanish', word_count: 0, due_count: 0, mastered_count: 0 },
  ] as never)
  start.mockResolvedValue(session() as never)
})

async function begin() {
  render(<CompanionChatPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Start chatting' }))
  return screen.findByLabelText('Message')
}

describe('CompanionChatPage', () => {
  it('offers nothing to chat with when the companion flag is off', async () => {
    recallSettings.mockResolvedValue({ ai_companion_enabled: false } as never)

    render(<CompanionChatPage />)

    expect(await screen.findByText(/switched off for this account/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start chatting' })).not.toBeInTheDocument()
    expect(start).not.toHaveBeenCalled()
  })

  it('shows both halves of an exchange once the assistant answers', async () => {
    const input = await begin()
    chat.mockResolvedValue({
      status: 'ok',
      user_turn: turn({ id: 1, content: 'Hola' }),
      assistant_turn: turn({ id: 2, role: 'assistant', content: '¡Hola! ¿Qué tal?' }),
      detail: null,
    } as never)

    fireEvent.change(input, { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('¡Hola! ¿Qué tal?')).toBeInTheDocument()
    expect(screen.getByText('Hola')).toBeInTheDocument()
    // Cleared only after the server accepted it.
    await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe(''))
  })

  it('keeps what was typed on screen when the model is unavailable', async () => {
    const input = await begin()
    chat.mockResolvedValue({
      status: 'unavailable',
      user_turn: turn({ id: 1, content: 'No me contestes' }),
      assistant_turn: null,
      detail: 'Ollama is unreachable',
    } as never)

    fireEvent.change(input, { target: { value: 'No me contestes' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('No me contestes')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('Ollama is unreachable')
  })

  it('reuses the same operation id when a failed send is retried', async () => {
    const input = await begin()
    chat.mockResolvedValue({
      status: 'unavailable',
      user_turn: turn({ id: 1, content: 'Hola' }),
      assistant_turn: null,
      detail: 'Temporarily down',
    } as never)

    fireEvent.change(input, { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByRole('alert')

    fireEvent.change(input, { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(chat).toHaveBeenCalledTimes(2))

    // Same id both times, so the backend returns the stored exchange rather
    // than asking the model the same thing twice.
    expect(chat.mock.calls[0][2]).toBe(chat.mock.calls[1][2])
    expect(chat.mock.calls[0][2]).toBeTruthy()
  })

  it('reports a deployment with no AI configured as disabled, not broken', async () => {
    const input = await begin()
    chat.mockResolvedValue({
      status: 'disabled',
      user_turn: turn({ id: 1, content: 'Hola' }),
      assistant_turn: null,
      detail: 'AI is not configured for this deployment, so the companion cannot reply.',
    } as never)

    fireEvent.change(input, { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('not configured')
  })
})
