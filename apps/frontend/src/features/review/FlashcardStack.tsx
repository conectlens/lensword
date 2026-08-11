import { useEffect, useRef, useState } from 'react'
import type { ReviewOutcome, Word } from '../../lib/types'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { PronunciationButton } from '../../components/ui/PronunciationButton'

/**
 * Flip-and-swipe practice (issue #338).
 *
 * **No new outcome vocabulary.** "Known" and "not known" are submitted as
 * the existing `correct` / `incorrect` outcomes, so scheduling stays where
 * it already lives — on the backend — and this mode is a different way to
 * answer the same question rather than a second grading system that would
 * drift from the first.
 *
 * **The gesture is never the only way.** A swipe is a pointer gesture with
 * no keyboard or screen-reader equivalent, so the same two decisions are
 * always present as real buttons, and the arrow keys drive them. The
 * gesture is an accelerant for people who like it, not the interface.
 *
 * **Answering requires flipping first.** Marking a word known while its
 * answer is still hidden records a recall that never happened, which
 * corrupts the schedule it feeds. The controls stay disabled until the card
 * is face up.
 */

/** How far a pointer must travel before it counts as a swipe, in px. */
const SWIPE_THRESHOLD = 80

export function FlashcardStack({
  word,
  position,
  total,
  busy = false,
  onAnswer,
}: {
  word: Word
  position: number
  total: number
  busy?: boolean
  onAnswer: (outcome: ReviewOutcome) => void
}) {
  // A new word arrives face down, and any half-finished drag belongs to the
  // card that just left. That reset is the caller's `key={word.id}` rather
  // than an effect here: remounting drops all three pieces of state at once,
  // where an effect would set them after a render in which the next word is
  // already showing the previous card's answer.
  const [revealed, setRevealed] = useState(false)
  const [dragX, setDragX] = useState(0)
  const dragStart = useRef<number | null>(null)

  function answer(outcome: ReviewOutcome) {
    if (!revealed || busy) return
    setDragX(0)
    onAnswer(outcome)
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'ArrowLeft') answer('incorrect')
      else if (event.key === 'ArrowRight') answer('correct')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  function onPointerDown(event: React.PointerEvent) {
    if (!revealed || busy) return
    dragStart.current = event.clientX
  }

  function onPointerMove(event: React.PointerEvent) {
    if (dragStart.current === null) return
    setDragX(event.clientX - dragStart.current)
  }

  function onPointerUp() {
    if (dragStart.current === null) return
    const travelled = dragX
    dragStart.current = null
    setDragX(0)

    if (travelled <= -SWIPE_THRESHOLD) answer('incorrect')
    else if (travelled >= SWIPE_THRESHOLD) answer('correct')
  }

  const committing = Math.abs(dragX) >= SWIPE_THRESHOLD

  return (
    <div className="flex w-full flex-col items-center gap-6">
      <p className="text-sm font-medium uppercase tracking-wide text-white/40" role="status">
        Card {position} of {total}
      </p>

      <Card
        className="flex w-full cursor-pointer select-none flex-col items-center gap-4 p-10 text-center transition-transform"
        style={{
          transform: `translateX(${dragX}px) rotate(${dragX / 30}deg)`,
          borderColor: committing ? (dragX > 0 ? 'rgb(34 197 94 / 0.6)' : 'rgb(239 68 68 / 0.6)') : undefined,
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {/* The card itself is the flip control: a button rather than a div
            with a click handler, so it is reachable by Tab and operable with
            Enter/Space without reimplementing either. */}
        <button
          type="button"
          className="flex w-full flex-col items-center gap-3"
          aria-pressed={revealed}
          onClick={() => setRevealed((value) => !value)}
        >
          <span className="font-display text-4xl font-bold text-white sm:text-5xl">{word.term}</span>
          <span className="text-sm text-white/40">{word.target_language}</span>

          {revealed ? (
            <span className="mt-4 border-t border-white/10 pt-4 text-2xl text-primary">
              {word.translations.join(', ') || 'No translation saved'}
            </span>
          ) : (
            <span className="mt-4 text-sm text-white/40">Tap to reveal the translation</span>
          )}
        </button>

        <PronunciationButton term={word.term} language={word.target_language} />
      </Card>

      {/* Announced rather than merely drawn: someone using a screen reader
          has no other signal that the card turned over. */}
      <p aria-live="polite" className="sr-only">
        {revealed
          ? `Answer shown: ${word.translations.join(', ') || 'no translation saved'}`
          : 'Answer hidden'}
      </p>

      <div className="grid w-full gap-3 sm:grid-cols-2">
        <Button
          size="lg"
          variant="secondary"
          icon="close"
          disabled={!revealed || busy}
          onClick={() => answer('incorrect')}
        >
          Don&apos;t know <span className="text-xs opacity-50">(←)</span>
        </Button>
        <Button size="lg" icon="check" disabled={!revealed || busy} onClick={() => answer('correct')}>
          Know it <span className="text-xs opacity-50">(→)</span>
        </Button>
      </div>

      <p className="text-xs text-white/30">
        {revealed ? 'Swipe the card, use the buttons, or press ← / →.' : 'Reveal the answer before marking it.'}
      </p>
    </div>
  )
}
