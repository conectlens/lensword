/**
 * Speaking a word in its own language (issue #335).
 *
 * **Why a mapping layer at all.** `SupportedLanguage` stores a human label
 * ("Spanish"), and `speechSynthesis` selects a voice by BCP-47 tag
 * ("es-ES"). Without a translation between the two, an utterance falls back
 * to the browser's default voice, which reads a Spanish word with an English
 * mouth — audibly wrong, and worse than no audio at all for someone using it
 * to learn a pronunciation. That is exactly what the one pre-existing
 * `speechSynthesis` call in the app does today, having set no `lang`.
 *
 * **Why the table is exhaustive rather than a lookup with a default.**
 * `SupportedLanguage` is a closed enum, so every member can be answered for
 * at compile time. `Record<SupportedLanguage, …>` makes adding a language to
 * the enum without deciding its locale a type error, rather than a silent
 * fall-through to English at runtime.
 *
 * `Other` maps to `null` deliberately. It is a placeholder meaning "not one
 * of the listed languages", not a language, so there is no honest locale to
 * guess — callers render a disabled control explaining that, instead of
 * speaking the word wrongly.
 */
import type { SupportedLanguage } from './types'

/** Preferred BCP-47 tag per language; `null` where none can be known. */
export const LANGUAGE_LOCALES: Record<SupportedLanguage, string | null> = {
  English: 'en-US',
  Spanish: 'es-ES',
  French: 'fr-FR',
  German: 'de-DE',
  Italian: 'it-IT',
  // pt-PT and pt-BR are both widely installed and differ audibly. The
  // preferred tag picks one, but `voiceFor` falls back to any `pt-*` voice,
  // so a device carrying only the other still speaks Portuguese rather than
  // nothing.
  Portuguese: 'pt-PT',
  Japanese: 'ja-JP',
  Korean: 'ko-KR',
  Turkish: 'tr-TR',
  Other: null,
}

export function localeFor(language: SupportedLanguage): string | null {
  return LANGUAGE_LOCALES[language] ?? null
}

/** The primary subtag: `es-ES` → `es`. */
function primarySubtag(locale: string): string {
  return locale.split('-')[0]!.toLowerCase()
}

/**
 * The best installed voice for a locale, or `null`.
 *
 * Exact tag first, then any voice sharing the primary subtag. A learner
 * with only `es-MX` installed should still hear Spanish; refusing because
 * the region differs would disable the feature over a distinction that
 * does not change whether the word is pronounced in the right language.
 */
export function voiceFor(
  voices: readonly SpeechSynthesisVoice[],
  locale: string,
): SpeechSynthesisVoice | null {
  const wanted = locale.toLowerCase()
  const exact = voices.find((voice) => voice.lang.toLowerCase() === wanted)
  if (exact) return exact

  const subtag = primarySubtag(locale)
  return voices.find((voice) => primarySubtag(voice.lang) === subtag) ?? null
}
