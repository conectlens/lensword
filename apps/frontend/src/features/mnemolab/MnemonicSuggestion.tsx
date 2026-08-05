import { useState } from 'react'
import { mnemonicsApi } from '../../lib/api'
import { Button } from '../../components/ui/Button'
import { Icon } from '../../components/ui/Icon'

/** Three outcomes the backend distinguishes, plus the two local ones.
 *
 *  `disabled` is deliberately terminal: no provider is configured, so a
 *  retry could not change the answer and offering one would be dishonest.
 *  `unavailable` is transient and always retryable. */
type SuggestionState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'disabled' }
  | { kind: 'unavailable'; detail: string }
  | { kind: 'ok'; text: string }

const DISABLED_HINT =
  'AI-generated suggestions are not available in this build — no LLM provider is configured.'

export function MnemonicSuggestion({ wordId, onUse }: { wordId: number; onUse?: (text: string) => void }) {
  const [state, setState] = useState<SuggestionState>({ kind: 'idle' })

  async function requestSuggestion() {
    setState({ kind: 'loading' })
    try {
      const result = await mnemonicsApi.suggest(wordId)
      if (result.status === 'ok') setState({ kind: 'ok', text: result.text })
      else if (result.status === 'unavailable') setState({ kind: 'unavailable', detail: result.detail })
      else setState({ kind: 'disabled' })
    } catch (err) {
      // The request itself failed (offline, backend down, 5xx). Same shape as
      // a provider outage from the user's point of view: transient, in place,
      // retryable — never an error page or a stack trace.
      setState({
        kind: 'unavailable',
        detail: err instanceof Error ? err.message : 'The suggestion request could not be completed.',
      })
    }
  }

  if (state.kind === 'disabled') {
    return (
      <span
        className="flex items-center gap-1 rounded-full bg-white/5 px-2 py-1 text-xs text-white/40"
        title={DISABLED_HINT}
      >
        <Icon name="info" className="text-sm" /> AI suggestions unavailable
      </span>
    )
  }

  return (
    <div className="flex flex-col items-end gap-2">
      {state.kind !== 'ok' && (
        <Button size="sm" variant="secondary" icon="auto_awesome" loading={state.kind === 'loading'} onClick={requestSuggestion}>
          {state.kind === 'loading' ? 'Thinking…' : 'Suggest with AI'}
        </Button>
      )}

      {state.kind === 'unavailable' && (
        <div className="flex flex-col items-end gap-1 text-right">
          <p className="text-xs text-warning">{state.detail}</p>
          <button onClick={requestSuggestion} className="text-xs text-white/60 underline hover:text-white">
            Try again
          </button>
        </div>
      )}

      {state.kind === 'ok' && (
        <div className="w-full rounded-lg border border-primary/40 bg-primary/10 p-4 text-left">
          <p className="text-white/80">{state.text}</p>
          <div className="mt-3 flex items-center gap-4 text-xs">
            {onUse && (
              <button onClick={() => onUse(state.text)} className="text-primary underline hover:brightness-110">
                Use this suggestion
              </button>
            )}
            <button onClick={requestSuggestion} className="text-white/60 underline hover:text-white">
              Suggest another
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
