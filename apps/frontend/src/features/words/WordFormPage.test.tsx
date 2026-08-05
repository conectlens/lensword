import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { WordFormPage } from './WordFormPage'
import { groupsApi } from '../../lib/api'
import type { Group } from '../../lib/types'

vi.mock('../../lib/api', () => ({
  groupsApi: { list: vi.fn(), addWord: vi.fn() },
  wordsApi: { get: vi.fn(), update: vi.fn() },
  aiVocabularyApi: { translateInContext: vi.fn(), regenerateField: vi.fn() },
}))

const list = vi.mocked(groupsApi.list)
const addWord = vi.mocked(groupsApi.addWord)

const group = (over: Partial<Group> = {}): Group => ({
  id: 1,
  name: 'Travel',
  target_language: 'Spanish',
  created_at: '2026-08-01T00:00:00',
  word_count: 0,
  mastered_count: 0,
  due_count: 0,
  last_reviewed_at: null,
  ...over,
})

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/words/new" element={<WordFormPage />} />
        <Route path="/groups/:groupId/words/new" element={<WordFormPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  list.mockReset()
  addWord.mockReset()
})

describe('WordFormPage without a group in the URL', () => {
  // This is the tray's "Add word" quick action's landing page (issue #82) —
  // routeFor('add_word') sends it here with no groupId, so the page has to
  // pick one itself rather than silently doing nothing on save.

  it('defaults to the first group and lets saving through', async () => {
    list.mockResolvedValue([group({ id: 1, name: 'Travel' }), group({ id: 2, name: 'Work' })])
    addWord.mockResolvedValue({} as never)

    renderAt('/words/new')

    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Group' })).toHaveValue('1'))
    fireEvent.change(screen.getByPlaceholderText('Enter the word'), { target: { value: 'hola' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save word' }))

    await waitFor(() => expect(addWord).toHaveBeenCalledWith(1, expect.objectContaining({ term: 'hola' })))
  })

  it('saves to whichever group was picked, not just the default', async () => {
    list.mockResolvedValue([group({ id: 1, name: 'Travel' }), group({ id: 2, name: 'Work' })])
    addWord.mockResolvedValue({} as never)

    renderAt('/words/new')

    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Group' })).toHaveValue('1'))
    fireEvent.change(screen.getByRole('combobox', { name: 'Group' }), { target: { value: '2' } })
    fireEvent.change(screen.getByPlaceholderText('Enter the word'), { target: { value: 'trabajo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save word' }))

    await waitFor(() => expect(addWord).toHaveBeenCalledWith(2, expect.objectContaining({ term: 'trabajo' })))
  })

  it('sends someone with no group yet to create one, rather than a dead-end save', async () => {
    list.mockResolvedValue([])

    renderAt('/words/new')

    expect(await screen.findByText(/create one/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /create one/i })).toHaveAttribute('href', '/groups')
    fireEvent.change(screen.getByPlaceholderText('Enter the word'), { target: { value: 'hola' } })
    expect(screen.getByRole('button', { name: 'Save word' })).toBeDisabled()
  })
})

describe('WordFormPage with a group in the URL', () => {
  it('shows no group picker — the group is already known', async () => {
    list.mockResolvedValue([group()])
    addWord.mockResolvedValue({} as never)

    renderAt('/groups/1/words/new')

    await screen.findByText('In Travel')
    expect(screen.queryByRole('combobox', { name: 'Group' })).not.toBeInTheDocument()
  })
})
