import { describe, expect, it } from 'vitest'

import { LANGUAGE_LOCALES, localeFor, voiceFor } from './speech'
import { LANGUAGES } from './types'

function voice(lang: string): SpeechSynthesisVoice {
  return { lang, name: `Voice ${lang}`, default: false, localService: true, voiceURI: lang } as SpeechSynthesisVoice
}

describe('localeFor', () => {
  it('answers for every language the app can store', () => {
    // The table is exhaustive by type, but a language added to the enum with
    // an accidentally-undefined entry would still typecheck against
    // `string | null`. This asserts the table is actually populated.
    for (const language of LANGUAGES) {
      expect(LANGUAGE_LOCALES).toHaveProperty(language)
    }
    expect(Object.keys(LANGUAGE_LOCALES).sort()).toEqual([...LANGUAGES].sort())
  })

  it('maps each real language to a BCP-47 tag', () => {
    expect(localeFor('Spanish')).toBe('es-ES')
    expect(localeFor('Japanese')).toBe('ja-JP')
    expect(localeFor('Turkish')).toBe('tr-TR')
  })

  it('refuses to guess a locale for the "Other" placeholder', () => {
    // "Other" means "not one of the listed languages", so there is no
    // honest locale — callers disable the control rather than mispronounce.
    expect(localeFor('Other')).toBeNull()
  })
})

describe('voiceFor', () => {
  it('prefers an exact locale match', () => {
    const voices = [voice('es-MX'), voice('es-ES'), voice('en-US')]
    expect(voiceFor(voices, 'es-ES')?.lang).toBe('es-ES')
  })

  it('falls back to any voice sharing the primary subtag', () => {
    // Only Mexican Spanish installed. Refusing over the region would
    // disable the feature on a device that can speak the language fine.
    const voices = [voice('es-MX'), voice('en-US')]
    expect(voiceFor(voices, 'es-ES')?.lang).toBe('es-MX')
  })

  it('matches case-insensitively, since platforms disagree on casing', () => {
    expect(voiceFor([voice('PT-br')], 'pt-PT')?.lang).toBe('PT-br')
  })

  it('returns null when nothing can speak the language', () => {
    expect(voiceFor([voice('en-US'), voice('fr-FR')], 'ja-JP')).toBeNull()
  })

  it('returns null against an empty voice list', () => {
    expect(voiceFor([], 'es-ES')).toBeNull()
  })
})
