import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PronunciationButton } from './PronunciationButton'

function voice(lang: string): SpeechSynthesisVoice {
  return { lang, name: `Voice ${lang}`, default: false, localService: true, voiceURI: lang } as SpeechSynthesisVoice
}

/** Install a fake `speechSynthesis`, or remove it entirely. */
function withSpeech(voices: SpeechSynthesisVoice[] | null) {
  if (voices === null) {
    // @ts-expect-error deleting an optional browser global for the test
    delete window.speechSynthesis
    return null
  }

  const synth = {
    getVoices: () => voices,
    speak: vi.fn(),
    cancel: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true, writable: true })
  Object.defineProperty(window, 'SpeechSynthesisUtterance', {
    value: class {
      lang = ''
      voice: SpeechSynthesisVoice | null = null
      constructor(public text: string) {}
    },
    configurable: true,
    writable: true,
  })
  return synth
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('PronunciationButton', () => {
  it('speaks the term in the language it is stored in', () => {
    const synth = withSpeech([voice('es-ES'), voice('en-US')])!

    render(<PronunciationButton term="correr" language="Spanish" />)
    fireEvent.click(screen.getByRole('button', { name: /Hear “correr” in Spanish/ }))

    expect(synth.speak).toHaveBeenCalledTimes(1)
    const utterance = synth.speak.mock.calls[0][0]
    expect(utterance.text).toBe('correr')
    expect(utterance.lang).toBe('es-ES')
    expect(utterance.voice?.lang).toBe('es-ES')
  })

  it('cancels first so a second press replays rather than queues', () => {
    const synth = withSpeech([voice('es-ES')])!

    render(<PronunciationButton term="correr" language="Spanish" />)
    fireEvent.click(screen.getByRole('button', { name: /Hear/ }))

    expect(synth.cancel).toHaveBeenCalled()
  })

  it('is disabled and says why when the browser has no speech support', () => {
    withSpeech(null)

    render(<PronunciationButton term="correr" language="Spanish" />)

    const button = screen.getByRole('button', { name: 'This browser cannot speak text.' })
    expect(button).toBeDisabled()
  })

  it('is disabled and says why for "Other" text with no script to guess from', () => {
    withSpeech([voice('en-US')])

    render(<PronunciationButton term="xyzzy" language="Other" />)

    expect(screen.getByRole('button', { name: /Pronunciation isn't available for “Other”/ })).toBeDisabled()
  })

  it('speaks an "Other"-language term by guessing a locale from its script', () => {
    // The reported bug: a Russian flashcard (target_language "Other", since
    // Russian isn't one of the nine listed languages) whose speaker button
    // did nothing. localeFor('Other') has no label to work from, but the
    // term itself is written in Cyrillic script.
    const synth = withSpeech([voice('ru-RU'), voice('en-US')])!

    render(<PronunciationButton term="привет" language="Other" />)
    const button = screen.getByRole('button', { name: /Hear “привет” in Other/ })
    expect(button).toBeEnabled()

    fireEvent.click(button)
    expect(synth.speak).toHaveBeenCalledTimes(1)
    expect(synth.speak.mock.calls[0][0].lang).toBe('ru')
  })

  it('is disabled and says why for an "Other" term whose guessed script has no installed voice', () => {
    withSpeech([voice('en-US')])

    render(<PronunciationButton term="привет" language="Other" />)

    expect(screen.getByRole('button', { name: 'No matching voice is installed on this device.' })).toBeDisabled()
  })

  it('is disabled and says why when no voice for that language is installed', () => {
    withSpeech([voice('en-US'), voice('fr-FR')])

    render(<PronunciationButton term="ねこ" language="Japanese" />)

    expect(screen.getByRole('button', { name: 'No Japanese voice is installed on this device.' })).toBeDisabled()
  })

  it('stays enabled while the browser has not populated its voice list yet', () => {
    // getVoices() is empty on first call in most browsers and fills in
    // later. Disabling on that would leave a permanently dead button on a
    // device with plenty of voices.
    const synth = withSpeech([])!

    render(<PronunciationButton term="correr" language="Spanish" />)
    const button = screen.getByRole('button', { name: /Hear “correr” in Spanish/ })
    expect(button).toBeEnabled()

    fireEvent.click(button)
    expect(synth.speak).toHaveBeenCalledTimes(1)
    expect(synth.speak.mock.calls[0][0].lang).toBe('es-ES')
  })
})
