import { localeFor } from '../../lib/speech'
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
  const locale = localeFor(language)

  const reason = !speech.supported
    ? 'This browser cannot speak text.'
    : locale === null
      ? `Pronunciation isn't available for “${language}”.`
      : !speech.canSpeak(locale)
        ? `No ${language} voice is installed on this device.`
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
