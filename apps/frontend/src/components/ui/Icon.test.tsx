/**
 * Icon names as a type rather than a string (issue #340).
 *
 * Migrating off the ligature font stopped a typo rendering as *literal text*,
 * which is what the original report was about. It did not stop the typo: a
 * `name: string` prop over a lookup table still resolved an unknown name to a
 * fallback glyph at runtime — quieter than before, and no easier to catch in
 * review.
 *
 * The real guarantee is therefore a compile-time one, which a runtime test
 * cannot observe directly. What it *can* pin is the surface that guarantee
 * rests on: that every name is a key of one table, that the escape hatch for
 * server-stored names is honest about unknown values, and that the fallback
 * never throws.
 */
import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

import { Icon, resolveIconName, type IconName } from './Icon'

it('renders an svg rather than text for a known name', () => {
  const { container } = render(<Icon name="meeting_room" />)

  // The ligature font rendered the *name* when it could not resolve a glyph.
  // An svg is proof the lookup happened rather than the string leaking out.
  expect(container.querySelector('svg')).toBeInTheDocument()
  expect(container.textContent).toBe('')
})

it('hides icons from assistive technology', () => {
  const { container } = render(<Icon name="check" />)

  // Every icon in this app sits beside its own text label, so announcing it
  // would only duplicate what was already read out.
  expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
})

it('passes a stored icon name through unchanged when the build has it', () => {
  // A room's icon is chosen by the user and stored on the server, so it
  // cannot be checked at compile time.
  expect(resolveIconName('meeting_room')).toBe('meeting_room')
})

it('falls back for a stored name this build no longer has', () => {
  // What happens when data outlives a rename. The alternative — trusting the
  // string — is the runtime crash this type exists to prevent.
  expect(resolveIconName('a_room_icon_from_2019')).toBe('unknown')
})

it('accepts an explicit fallback for callers with a better default', () => {
  expect(resolveIconName('gone', 'meeting_room')).toBe('meeting_room')
})

it('still renders something if an unchecked name reaches it at runtime', () => {
  // Defence in depth: `IconName` makes this unreachable from typed code, but
  // a missing glyph is a better outcome than a crash mid-render.
  const { container } = render(<Icon name={'not_an_icon' as IconName} />)

  expect(container.querySelector('svg')).toBeInTheDocument()
})

it('defines every icon name its own call sites reference', () => {
  // `check_circle` and `radio_button_unchecked` were referenced by
  // OAuthAuthorizePage and never defined, so both had been silently rendering
  // the fallback until `IconName` turned that into a compile error. This
  // guards the two that were actually found rather than restating the type.
  for (const name of ['check_circle', 'radio_button_unchecked'] as IconName[]) {
    expect(resolveIconName(name)).toBe(name)
  }
})
