import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { GroupsPage } from './GroupsPage'
import { groupsApi } from '../../lib/api'
import { selectOption } from '../../test/selectOption'

vi.mock('../../lib/api', () => ({
  groupsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() },
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

const list = vi.mocked(groupsApi.list)
const update = vi.mocked(groupsApi.update)

const group = (over = {}) => ({
  id: 1,
  name: 'Spanish 1',
  target_language: 'Spanish' as const,
  created_at: '2026-08-01T00:00:00',
  word_count: 3,
  mastered_count: 0,
  due_count: 0,
  last_reviewed_at: null,
  ...over,
})

beforeEach(() => {
  list.mockReset()
  update.mockReset()
  list.mockResolvedValue([group()] as never)
  update.mockResolvedValue(group() as never)
})

async function openEditor() {
  render(<GroupsPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Spanish 1' }))
  return screen.findByRole('dialog')
}

describe('GroupsPage editing', () => {
  it('opens an editor prefilled with the group as it stands', async () => {
    await openEditor()

    expect(screen.getByLabelText('Group name')).toHaveValue('Spanish 1')
    expect(screen.getByRole('combobox', { name: 'Target language' })).toHaveTextContent('Spanish')
  })

  it('saves a renamed group', async () => {
    await openEditor()

    fireEvent.change(screen.getByLabelText('Group name'), { target: { value: 'Spanish Verbs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(1, {
        name: 'Spanish Verbs',
        target_language: 'Spanish',
      }),
    )
  })

  it('saves a changed target language', async () => {
    await openEditor()

    await selectOption('Target language', 'French')
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(1, { name: 'Spanish 1', target_language: 'French' }),
    )
  })

  it('says up front that existing words keep their own language', async () => {
    await openEditor()

    expect(screen.queryByText(/stay marked as/i)).not.toBeInTheDocument()

    await selectOption('Target language', 'French')

    expect(await screen.findByText(/3 words already in this group/i)).toBeInTheDocument()
    expect(screen.getByText(/stay marked as Spanish/i)).toBeInTheDocument()
  })

  it('keeps the editor open and explains when saving fails', async () => {
    update.mockRejectedValue(new Error('nope'))
    await openEditor()

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save those changes')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
