import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import {
  captureScreenRegionAndOcr,
  isScreenCaptureDesktopAvailable,
} from '../../lib/ocrCapture'

/**
 * Screen-region capture and OCR review, feeding into the same textarea
 * `SourceLoader` fills from a file or URL (issue #84).
 *
 * The bundled OCR engine (`ocrs`) does not report a per-line confidence
 * score — see `ocr_capture.rs`'s module docs for why. Rather than fabricate
 * one, every detected line is shown as an editable, uncheckable row: the
 * review this issue requires happens by construction, not by a threshold
 * that would be guessing. Nothing reaches the shared textarea — and from
 * there, nothing reaches storage — until the confirm button is pressed.
 */

type ReviewLine = {
  text: string
  included: boolean
}

type Props = {
  onLoaded: (text: string) => void
}

export function OcrCapture({ onLoaded }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lines, setLines] = useState<ReviewLine[] | null>(null)

  if (!isScreenCaptureDesktopAvailable()) return null

  async function capture() {
    setBusy(true)
    setError(null)
    setLines(null)
    try {
      const result = await captureScreenRegionAndOcr()
      if (result.status === 'ok') {
        setLines(result.lines.map((line) => ({ text: line.text, included: true })))
      } else if (result.status === 'cancelled') {
        // The user opened the region picker and pressed Escape. Not an error.
      } else if (result.status === 'empty') {
        setError('No text was found in that region.')
      } else {
        setError(result.detail ?? 'Screen capture is not available on this platform.')
      }
    } catch {
      setError('Could not capture the screen.')
    } finally {
      setBusy(false)
    }
  }

  function updateLine(index: number, patch: Partial<ReviewLine>) {
    setLines((current) =>
      current?.map((line, i) => (i === index ? { ...line, ...patch } : line)) ?? null,
    )
  }

  function confirm() {
    if (!lines) return
    const text = lines
      .filter((line) => line.included && line.text.trim())
      .map((line) => line.text)
      .join('\n')
    onLoaded(text)
    setLines(null)
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" icon="screenshot_monitor" loading={busy} onClick={() => void capture()}>
          Capture screen region
        </Button>
        <span className="text-sm text-white/40">Drag to select a region; every line stays editable before use</span>
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}

      {lines && lines.length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-white/10 bg-white/5 p-3">
          <p className="text-sm text-white/60">
            Correct anything the capture misread, or uncheck a line to drop it. Nothing is used until you confirm.
          </p>
          {lines.map((line, index) => (
            <label key={index} className="flex items-center gap-2 text-white">
              <input
                type="checkbox"
                aria-label={`Include line ${index + 1}`}
                checked={line.included}
                onChange={(event) => updateLine(index, { included: event.target.checked })}
              />
              <input
                type="text"
                value={line.text}
                disabled={!line.included}
                onChange={(event) => updateLine(index, { text: event.target.value })}
                className="min-w-0 flex-1 rounded border border-white/10 bg-white/5 p-1.5 text-white disabled:opacity-40"
              />
            </label>
          ))}
          <Button onClick={confirm} disabled={!lines.some((line) => line.included && line.text.trim())}>
            Use selected text
          </Button>
        </div>
      )}
    </div>
  )
}
