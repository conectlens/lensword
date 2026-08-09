import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { BulkEditBar } from './BulkEditBar'
import { wordsApi } from '../../lib/api'
import { selectOption } from '../../test/selectOption'

vi.mock('../../lib/api', () => ({
  wordsApi: { bulkEdit: vi.fn() },
}))

const bulkEdit = vi.mocked(wordsApi.bulkEdit)

beforeEach(() => {
  bulkEdit.mockReset()
  bulkEdit.mockResolvedValue({ updated: 2, skipped: [] })
})

describe('BulkEditBar', () => {
  it('will not apply when nothing has been set', async () => {
    // A form that wiped every field it did not mention would destroy work with
    // one careless apply, and there is no undo here.
    render(<BulkEditBar selectedIds={[1, 2]} onApplied={vi.fn()} onClear={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Apply to selected' })).toBeDisabled()
  })

  it('sends only the fields that were set', async () => {
    render(<BulkEditBar selectedIds={[1, 2]} onApplied={vi.fn()} onClear={vi.fn()} />)
    await selectOption('Bulk CEFR level', 'B1')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }))

    await waitFor(() =>
      expect(bulkEdit).toHaveBeenCalledWith([1, 2], {
        cefr_level: 'B1',
        part_of_speech: undefined,
      }),
    )
  })

  it('offers no control that could overwrite terms', async () => {
    // Excluded on purpose: overwriting forty terms with one value is a mistake
    // waiting to be made irreversibly.
    render(<BulkEditBar selectedIds={[1]} onApplied={vi.fn()} onClear={vi.fn()} />)

    expect(screen.queryByLabelText(/term/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/translation/i)).not.toBeInTheDocument()
  })

  it('reports how many cards were changed', async () => {
    render(<BulkEditBar selectedIds={[1, 2]} onApplied={vi.fn()} onClear={vi.fn()} />)
    await selectOption('Bulk CEFR level', 'B1')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Updated 2 cards.')
  })

  it('says when some cards could not be changed rather than swallowing it', async () => {
    // A bulk edit that quietly did less than it was asked is worse than one
    // that says so.
    bulkEdit.mockResolvedValue({ updated: 1, skipped: [7] })

    render(<BulkEditBar selectedIds={[1, 7]} onApplied={vi.fn()} onClear={vi.fn()} />)
    await selectOption('Bulk CEFR level', 'B1')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }))

    expect(await screen.findByRole('status')).toHaveTextContent('1 could not be changed')
  })

  it('reports a failure instead of appearing to have applied', async () => {
    bulkEdit.mockRejectedValue(new Error('offline'))
    const onApplied = vi.fn()

    render(<BulkEditBar selectedIds={[1]} onApplied={onApplied} onClear={vi.fn()} />)
    await selectOption('Bulk CEFR level', 'B1')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Could not apply')
    expect(onApplied).not.toHaveBeenCalled()
  })
})
