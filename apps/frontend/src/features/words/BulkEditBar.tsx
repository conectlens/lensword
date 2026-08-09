import { useState } from 'react'
import { wordsApi } from '../../lib/api'
import { Button } from '../../components/ui/Button'
import { ANY_OPTION, Select } from '../../components/ui/Select'

/**
 * Setting one field across several cards at once (issue #140).
 *
 * Only fields a bulk edit can sensibly set are offered. Term and translations
 * are missing on purpose: those are what make a card that card, and a control
 * that could overwrite forty terms with one value is a mistake waiting to be
 * made irreversibly.
 *
 * A field left blank means "leave alone" rather than "clear". A form that
 * wiped every field it did not mention would destroy work with one careless
 * apply, and there is no undo here.
 */

const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']

type Props = {
  selectedIds: number[]
  onApplied: () => void
  onClear: () => void
}

export function BulkEditBar({ selectedIds, onApplied, onClear }: Props) {
  const [level, setLevel] = useState('')
  const [partOfSpeech, setPartOfSpeech] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const nothingToSet = !level && !partOfSpeech.trim()

  async function apply() {
    setBusy(true)
    setResult(null)
    try {
      const response = await wordsApi.bulkEdit(selectedIds, {
        // Undefined rather than null: null would be a request to clear the
        // field, and an untouched control must not do that.
        cefr_level: level || undefined,
        part_of_speech: partOfSpeech.trim() || undefined,
      })
      // Skipped ids are reported rather than swallowed — a bulk edit that
      // quietly did less than it was asked is worse than one that says so.
      setResult(
        response.skipped.length > 0
          ? `Updated ${response.updated}. ${response.skipped.length} could not be changed.`
          : `Updated ${response.updated} card${response.updated === 1 ? '' : 's'}.`,
      )
      setLevel('')
      setPartOfSpeech('')
      onApplied()
    } catch {
      setResult('Could not apply those changes.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-white/5 p-3">
      <span className="text-sm font-semibold text-white">
        {selectedIds.length} selected
      </span>

      <label className="text-sm text-white/70">
        CEFR
        <Select
          size="sm"
          className="ml-2"
          aria-label="Bulk CEFR level"
          value={level || ANY_OPTION}
          onValueChange={(next) => setLevel(next === ANY_OPTION ? '' : next)}
          options={[{ value: ANY_OPTION, label: 'Leave unchanged' }, ...LEVELS.map((value) => ({ value, label: value }))]}
        />
      </label>

      <input
        value={partOfSpeech}
        onChange={(event) => setPartOfSpeech(event.target.value)}
        placeholder="Part of speech"
        aria-label="Bulk part of speech"
        className="rounded-lg border border-white/10 bg-white/5 p-1.5 text-sm text-white"
      />

      <Button size="sm" loading={busy} disabled={nothingToSet} onClick={() => void apply()}>
        Apply to selected
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear selection
      </Button>

      {result && (
        <span role="status" className="text-sm text-white/60">
          {result}
        </span>
      )}
    </div>
  )
}
