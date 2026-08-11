import { localeFor, localeForText } from '../../lib/speech'
import { useSpeech } from '../../lib/useSpeech'
import type { SupportedLanguage } from '../../lib/types'
import { Button } from './Button'

/**
 * Hear a word in its own language (issue #335).
 *
 * When playback isn't possible the control stays visible and disabled, with
 * the reason on its `title`/`aria-label`, rather than disappearing or
 * silently doing nothing. A button that looks live and produces no sound is
 * indistinguishable from broken audio hardware, and someone will spend real
 * time checking their speakers.
 *
 * "Other" words fall back to a locale guessed from the term's own script
 * (`localeForText`) rather than being disabled outright — `localeFor`
 * correctly refuses to guess from the placeholder label alone, but a term
 * actually written in, say, Cyrillic script is real evidence `localeFor`
 * never sees. Without this, every word in a language outside the fixed
 * nine-language list (Russian, Arabic, Chinese, ...) was permanently
 * silent — reported against a Russian flashcard whose target_language is
 * "Other".
 */
export function PronunciationButton({
  term,
  language,
  className = '',
}: {
  term: string
  language: SupportedLanguage
  className?: string
}) {
  const speech = useSpeech()
  const labeledLocale = localeFor(language)
  const guessedLocale = labeledLocale === null ? localeForText(term) : null
  const locale = labeledLocale ?? guessedLocale

  const reason = !speech.supported
    ? 'This browser cannot speak text.'
    : locale === null
      ? `Pronunciation isn't available for “${language}”.`
      : !speech.canSpeak(locale)
        ? guessedLocale
          ? 'No matching voice is installed on this device.'
          : `No ${language} voice is installed on this device.`
        : null

  const label = reason ?? `Hear “${term}” in ${language}`

  return (
    <Button
      variant="ghost"
      size="sm"
      icon="volume_up"
      className={className}
      disabled={reason !== null}
      aria-label={label}
      title={label}
      onClick={() => locale && speech.speak(term, locale)}
    />
  )
}
