import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ImportPage } from './ImportPage'

const { list, preview, commit } = vi.hoisted(() => ({ list: vi.fn(), preview: vi.fn(), commit: vi.fn() }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useParams: () => ({ groupId: '1' }) }))
vi.mock('../../lib/api', () => ({ groupsApi: { list }, importsApi: { preview, commit, parseFile: vi.fn() } }))

describe('ImportPage', () => {
  beforeEach(() => { list.mockResolvedValue([{ id: 1, name: 'Spanish', target_language: 'Spanish' }]); preview.mockResolvedValue({ records: [{ term: 'hola', translations: ['hello'], definition: null, part_of_speech: null, cefr_level: null, pronunciation: null, source_language: 'Unknown', status: 'ready', duplicate_of: null, provider: null, model: null }] }) })
  it('previews records and commits the reviewed set', async () => {
    render(<ImportPage />)
    await screen.findByText('Import vocabulary')
    fireEvent.click(screen.getByText('Preview import'))
    await screen.findByText('Review import')
    expect(screen.getByText('hola')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Commit reviewed records'))
    await waitFor(() => expect(commit).toHaveBeenCalled())
  })
})
