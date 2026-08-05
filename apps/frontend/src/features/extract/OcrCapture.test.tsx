import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { OcrCapture } from './OcrCapture'
import { captureScreenRegionAndOcr, isScreenCaptureDesktopAvailable } from '../../lib/ocrCapture'

vi.mock('../../lib/ocrCapture', () => ({
  captureScreenRegionAndOcr: vi.fn(),
  isScreenCaptureDesktopAvailable: vi.fn(),
}))

const capture = vi.mocked(captureScreenRegionAndOcr)
const available = vi.mocked(isScreenCaptureDesktopAvailable)

beforeEach(() => {
  capture.mockReset()
  available.mockReset()
  available.mockReturnValue(true)
})

describe('OcrCapture', () => {
  it('renders nothing outside the desktop shell', () => {
    available.mockReturnValue(false)
    render(<OcrCapture onLoaded={vi.fn()} />)

    expect(screen.queryByRole('button', { name: /Capture screen region/ })).not.toBeInTheDocument()
  })

  it('shows every detected line as editable and checked by default', async () => {
    capture.mockResolvedValue({
      status: 'ok',
      lines: [
        { text: 'hola', boundingBox: { left: 0, top: 0, right: 10, bottom: 10 }, confidence: null },
        { text: 'mundo', boundingBox: { left: 0, top: 12, right: 10, bottom: 20 }, confidence: null },
      ],
      detail: null,
    })

    render(<OcrCapture onLoaded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Capture screen region/ }))

    await waitFor(() => expect(screen.getByDisplayValue('hola')).toBeInTheDocument())
    expect(screen.getByDisplayValue('mundo')).toBeInTheDocument()
    expect(screen.getByLabelText('Include line 1')).toBeChecked()
  })

  it('nothing is used until confirm is pressed', async () => {
    capture.mockResolvedValue({
      status: 'ok',
      lines: [{ text: 'hola', boundingBox: { left: 0, top: 0, right: 10, bottom: 10 }, confidence: null }],
      detail: null,
    })
    const onLoaded = vi.fn()

    render(<OcrCapture onLoaded={onLoaded} />)
    fireEvent.click(screen.getByRole('button', { name: /Capture screen region/ }))
    await waitFor(() => expect(screen.getByDisplayValue('hola')).toBeInTheDocument())

    expect(onLoaded).not.toHaveBeenCalled()
  })

  it('confirm joins only the checked, edited lines', async () => {
    capture.mockResolvedValue({
      status: 'ok',
      lines: [
        { text: 'hola', boundingBox: { left: 0, top: 0, right: 10, bottom: 10 }, confidence: null },
        { text: 'mundo raro', boundingBox: { left: 0, top: 12, right: 10, bottom: 20 }, confidence: null },
      ],
      detail: null,
    })
    const onLoaded = vi.fn()

    render(<OcrCapture onLoaded={onLoaded} />)
    fireEvent.click(screen.getByRole('button', { name: /Capture screen region/ }))
    await waitFor(() => expect(screen.getByDisplayValue('hola')).toBeInTheDocument())

    // Correct a misread.
    fireEvent.change(screen.getByDisplayValue('mundo raro'), { target: { value: 'mundo' } })
    // Drop the first line entirely.
    fireEvent.click(screen.getByLabelText('Include line 1'))

    fireEvent.click(screen.getByRole('button', { name: /Use selected text/ }))

    expect(onLoaded).toHaveBeenCalledWith('mundo')
  })

  it('a cancelled selection shows no error', async () => {
    capture.mockResolvedValue({ status: 'cancelled', lines: [], detail: null })

    render(<OcrCapture onLoaded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Capture screen region/ }))

    await waitFor(() => expect(capture).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('an empty result says so rather than showing a blank review list', async () => {
    capture.mockResolvedValue({ status: 'empty', lines: [], detail: null })

    render(<OcrCapture onLoaded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Capture screen region/ }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/No text was found/))
  })

  it('shows the platform detail when capture is unsupported', async () => {
    capture.mockResolvedValue({
      status: 'unsupported',
      lines: [],
      detail: 'screen capture is not yet implemented on windows',
    })

    render(<OcrCapture onLoaded={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Capture screen region/ }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('screen capture is not yet implemented on windows'),
    )
  })
})
