import { useEffect, useState } from 'react'
import { voiceFor } from './speech'

/**
 * `window.speechSynthesis`, made usable from React (issue #335).
 *
 * The awkward part this exists to hide: the voice list is populated
 * asynchronously. On most browsers `getVoices()` returns an empty array on
 * first call and fills in later, firing `voiceschanged`. A component that
 * reads it once at mount therefore concludes "no voices" and disables
 * itself permanently, on a device that has plenty. Subscribing to the event
 * and re-rendering is the whole reason this is a hook rather than a
 * function.
 */
export interface Speech {
  /** The browser exposes a speech API at all. */
  supported: boolean
  /** Voices currently known. Empty until the browser has populated them. */
  voices: SpeechSynthesisVoice[]
  /** Whether a voice exists that can speak this locale. */
  canSpeak: (locale: string) => boolean
  /** Speak `text` in `locale`. No-op when nothing can speak it. */
  speak: (text: string, locale: string) => void
}

export function useSpeech(): Speech {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])

  useEffect(() => {
    if (!supported) return

    const synth = window.speechSynthesis
    const read = () => setVoices(synth.getVoices())

    read()
    synth.addEventListener?.('voiceschanged', read)
    return () => synth.removeEventListener?.('voiceschanged', read)
  }, [supported])

  function canSpeak(locale: string): boolean {
    // Before the browser has populated its list there is nothing to check
    // against, and reporting "cannot speak" would disable a control that is
    // about to work. Treat an empty list as "unknown, allow it": the worst
    // case is one utterance in a default voice, against a permanently dead
    // button in the alternative.
    if (!supported) return false
    return voices.length === 0 || voiceFor(voices, locale) !== null
  }

  function speak(text: string, locale: string): void {
    if (!supported || !text.trim()) return

    const synth = window.speechSynthesis
    // Cancel first: pressing the button twice should replay the word, not
    // queue a second reading behind the first.
    synth.cancel()

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = locale
    const voice = voiceFor(voices, locale)
    if (voice) utterance.voice = voice
    synth.speak(utterance)
  }

  return { supported, voices, canSpeak, speak }
}
