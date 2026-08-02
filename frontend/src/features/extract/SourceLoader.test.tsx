import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { SourceLoader } from './SourceLoader'
import { importsApi, ApiRequestError } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    importsApi: { parseFile: vi.fn(), parseUrl: vi.fn() },
  }
})

const parseFile = vi.mocked(importsApi.parseFile)
const parseUrl = vi.mocked(importsApi.parseUrl)

beforeEach(() => {
  parseFile.mockReset()
  parseUrl.mockReset()
})

describe('SourceLoader', () => {
  it('puts fetched text in front of the user rather than extracting it directly', async () => {
    // A parser can misread a PDF's columns or pull a site's navigation menu.
    // Feeding that to the AI unseen would produce vocabulary from text nobody
    // ever read.
    parseUrl.mockResolvedValue({ records: [{ term: 'El gato duerme.', translations: [] }] })
    const onLoaded = vi.fn()

    render(<SourceLoader onLoaded={onLoaded} />)
    fireEvent.change(screen.getByLabelText('Import from URL'), {
      target: { value: 'https://example.com/article' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Fetch page/ }))

    await waitFor(() => expect(onLoaded).toHaveBeenCalledWith('El gato duerme.'))
  })

  it('shows the server refusal verbatim instead of a generic message', async () => {
    // Refusals from the URL guard are written for the person reading them.
    // Replacing "only http and https URLs can be imported" with "something
    // went wrong" throws away the only thing that tells them what to fix.
    parseUrl.mockRejectedValue(new ApiRequestError(422, 'Only http and https URLs can be imported'))

    render(<SourceLoader onLoaded={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Import from URL'), {
      target: { value: 'file:///etc/passwd' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Fetch page/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Only http and https URLs can be imported',
    )
  })

  it('does not fetch an empty URL', () => {
    render(<SourceLoader onLoaded={vi.fn()} />)

    expect(screen.getByRole('button', { name: /Fetch page/ })).toBeDisabled()
    expect(parseUrl).not.toHaveBeenCalled()
  })

  it('loads a file through the parser and hands back its text', async () => {
    parseFile.mockResolvedValue({ records: [{ term: 'La casa', translations: [] }] })
    const onLoaded = vi.fn()

    render(<SourceLoader onLoaded={onLoaded} />)
    const input = screen.getByLabelText('Import from file')
    fireEvent.change(input, {
      target: { files: [new File(['x'], 'notes.txt', { type: 'text/plain' })] },
    })

    await waitFor(() => expect(onLoaded).toHaveBeenCalledWith('La casa'))
  })

  it('reports a failed file read rather than silently loading nothing', async () => {
    parseFile.mockRejectedValue(new ApiRequestError(422, 'No readable text found in file'))
    const onLoaded = vi.fn()

    render(<SourceLoader onLoaded={onLoaded} />)
    fireEvent.change(screen.getByLabelText('Import from file'), {
      target: { files: [new File(['x'], 'empty.pdf', { type: 'application/pdf' })] },
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('No readable text found in file')
    expect(onLoaded).not.toHaveBeenCalled()
  })

  it('clears an earlier error when a later load succeeds', async () => {
    parseUrl
      .mockRejectedValueOnce(new ApiRequestError(502, 'That page could not be fetched'))
      .mockResolvedValueOnce({ records: [{ term: 'ok', translations: [] }] })

    render(<SourceLoader onLoaded={vi.fn()} />)
    const field = screen.getByLabelText('Import from URL')

    fireEvent.change(field, { target: { value: 'https://example.com/gone' } })
    fireEvent.click(screen.getByRole('button', { name: /Fetch page/ }))
    await screen.findByRole('alert')

    fireEvent.change(field, { target: { value: 'https://example.com/good' } })
    fireEvent.click(screen.getByRole('button', { name: /Fetch page/ }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })
})
