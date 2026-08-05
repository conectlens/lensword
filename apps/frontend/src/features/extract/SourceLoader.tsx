import { useRef, useState } from 'react'
import { importsApi, ApiRequestError } from '../../lib/api'
import { Button } from '../../components/ui/Button'

/**
 * Getting a passage into the Extract page from a file or a URL (issue #145).
 *
 * The backend already parsed all of these formats (#85); what was missing was
 * any way to reach it from this page. Both paths end in the same place — text
 * in the textarea the user can read and edit before anything is extracted.
 * That matters: a parser can misread a PDF's columns or pull a site's
 * navigation menu, and silently feeding that to the AI would produce
 * vocabulary from text nobody ever saw.
 */

// Mirrors the backend parser registry. Advisory only — the server decides what
// it can actually read, and a browser that ignores `accept` must still get a
// real answer rather than a broken upload.
const ACCEPTED = '.txt,.md,.csv,.json,.srt,.vtt,.pdf,.epub,.docx,.html,.htm'

type Props = {
  onLoaded: (text: string) => void
}

export function SourceLoader({ onLoaded }: Props) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<'file' | 'url' | null>(null)
  const [error, setError] = useState<string | null>(null)

  function report(err: unknown, fallback: string) {
    // The server's message is shown as-is: refusals here are deliberately
    // written for the person reading them ("only http and https URLs can be
    // imported"), and replacing them with a generic string would throw that
    // away.
    setError(err instanceof ApiRequestError ? err.message : fallback)
  }

  async function loadFile(file: File) {
    setBusy('file')
    setError(null)
    try {
      const parsed = await importsApi.parseFile(file)
      onLoaded(parsed.records.map((record) => record.term).join('\n'))
    } catch (err) {
      report(err, 'Could not read that file.')
    } finally {
      setBusy(null)
      // Cleared so choosing the same file twice fires a change event the
      // second time.
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function loadUrl() {
    if (!url.trim()) return
    setBusy('url')
    setError(null)
    try {
      const parsed = await importsApi.parseUrl(url.trim())
      onLoaded(parsed.records.map((record) => record.term).join('\n'))
      setUrl('')
    } catch (err) {
      report(err, 'Could not fetch that page.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED}
          aria-label="Import from file"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void loadFile(file)
          }}
        />
        <Button
          variant="secondary"
          icon="upload_file"
          loading={busy === 'file'}
          onClick={() => fileInput.current?.click()}
        >
          Load from file
        </Button>
        <span className="text-sm text-white/40">PDF, EPUB, DOCX, subtitles, HTML, text</span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void loadUrl()
          }}
          placeholder="https://example.com/article"
          aria-label="Import from URL"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 p-2 text-white"
        />
        <Button
          variant="secondary"
          icon="link"
          loading={busy === 'url'}
          disabled={!url.trim()}
          onClick={() => void loadUrl()}
        >
          Fetch page
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}
    </div>
  )
}
