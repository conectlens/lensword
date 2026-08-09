import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { FlashcardStack } from './FlashcardStack'
import type { Word } from '../../lib/types'

const word = (over: Partial<Word> = {}): Word =>
  ({
    id: 1,
    group_id: 1,
    term: 'correr',
    target_language: 'Spanish',
    translations: ['to run'],
    review_state: { repetitions: 0 },
    ...over,
  }) as Word

// jsdom implements no `PointerEvent`, so `fireEvent.pointerDown` falls back
// to a plain Event and silently drops `clientX` — every drag would measure
// NaN and no swipe would ever register, in a component that works fine in a
// browser. MouseEvent carries the coordinates the handlers actually read.
beforeEach(() => {
  const globals = window as unknown as { PointerEvent?: unknown; MouseEvent: unknown }
  if (!globals.PointerEvent) {
    Object.defineProperty(window, 'PointerEvent', {
      value: globals.MouseEvent,
      configurable: true,
      writable: true,
    })
  }

  // The card renders a PronunciationButton, which reads speechSynthesis.
  Object.defineProperty(window, 'speechSynthesis', {
    value: { getVoices: () => [], speak: vi.fn(), cancel: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() },
    configurable: true,
    writable: true,
  })
})

/** The card face itself — the only control carrying `aria-pressed`. */
function reveal() {
  fireEvent.click(screen.getByRole('button', { pressed: false }))
}

/** A pointer drag of `dx` px across the card. */
function swipe(dx: number) {
  const card = screen.getByText('correr').closest('[class*="cursor-pointer"]')!
  fireEvent.pointerDown(card, { clientX: 0 })
  fireEvent.pointerMove(card, { clientX: dx })
  fireEvent.pointerUp(card, { clientX: dx })
}

describe('FlashcardStack', () => {
  it('hides the answer until the card is flipped', () => {
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={vi.fn()} />)

    expect(screen.queryByText('to run')).not.toBeInTheDocument()
    reveal()
    expect(screen.getByText('to run')).toBeInTheDocument()
  })

  it('announces the flip state for screen readers', () => {
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={vi.fn()} />)

    expect(screen.getByText('Answer hidden')).toBeInTheDocument()
    reveal()
    expect(screen.getByText('Answer shown: to run')).toBeInTheDocument()
  })

  it('refuses to grade a card whose answer is still hidden', () => {
    // Marking a word known while the answer is hidden records a recall that
    // never happened, and the schedule is computed from those records.
    const onAnswer = vi.fn()
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={onAnswer} />)

    expect(screen.getByRole('button', { name: /Know it/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Don't know/ })).toBeDisabled()

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    swipe(200)
    expect(onAnswer).not.toHaveBeenCalled()
  })

  it('maps the buttons onto the existing outcome vocabulary', () => {
    const onAnswer = vi.fn()
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={onAnswer} />)
    reveal()

    fireEvent.click(screen.getByRole('button', { name: /Know it/ }))
    expect(onAnswer).toHaveBeenCalledWith('correct')

    fireEvent.click(screen.getByRole('button', { name: /Don't know/ }))
    expect(onAnswer).toHaveBeenLastCalledWith('incorrect')
  })

  it('maps the arrow keys onto the same two outcomes', () => {
    const onAnswer = vi.fn()
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={onAnswer} />)
    reveal()

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(onAnswer).toHaveBeenCalledWith('correct')

    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(onAnswer).toHaveBeenLastCalledWith('incorrect')
  })

  it('maps a swipe right to known and a swipe left to not known', () => {
    const onAnswer = vi.fn()
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={onAnswer} />)
    reveal()

    swipe(200)
    expect(onAnswer).toHaveBeenCalledWith('correct')

    swipe(-200)
    expect(onAnswer).toHaveBeenLastCalledWith('incorrect')
  })

  it('ignores a drag too short to be a deliberate swipe', () => {
    const onAnswer = vi.fn()
    render(<FlashcardStack word={word()} position={1} total={3} onAnswer={onAnswer} />)
    reveal()

    swipe(20)
    expect(onAnswer).not.toHaveBeenCalled()
  })

  it('turns the next card face down again', () => {
    // Keyed exactly as the session page renders it: the reset is a remount,
    // not an effect, so the next card can never paint the previous card's
    // answer for a frame.
    const first = word()
    const { rerender } = render(
      <FlashcardStack key={first.id} word={first} position={1} total={3} onAnswer={vi.fn()} />,
    )
    reveal()
    expect(screen.getByText('to run')).toBeInTheDocument()

    const second = word({ id: 2, term: 'hablar', translations: ['to speak'] })
    rerender(
      <FlashcardStack key={second.id} word={second} position={2} total={3} onAnswer={vi.fn()} />,
    )

    expect(screen.queryByText('to speak')).not.toBeInTheDocument()
    expect(screen.getByText('Answer hidden')).toBeInTheDocument()
  })

  it('does not submit twice while an answer is in flight', () => {
    const onAnswer = vi.fn()
    render(<FlashcardStack word={word()} position={1} total={3} busy onAnswer={onAnswer} />)
    reveal()

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(onAnswer).not.toHaveBeenCalled()
  })
})
