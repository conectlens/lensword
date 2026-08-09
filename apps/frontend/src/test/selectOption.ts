/**
 * Choosing a value from the themed `Select` in a test (issue #341).
 *
 * `fireEvent.change(getByLabelText(…), { target: { value } })` worked while
 * the component wrapped a native `<select>`, because a native select *is* a
 * form control with a value. The open list is now ordinary markup, so a test
 * has to do what a person does: open the dropdown, then pick the option.
 *
 * Keyboard rather than pointer, deliberately. jsdom reports every element as
 * zero-sized and implements no pointer capture, so pointer-driven opening is
 * the flaky path — and driving the control the way a keyboard user does means
 * these tests also fail if keyboard access regresses, which the issue lists as
 * an acceptance criterion.
 */
import { fireEvent, screen, within } from '@testing-library/react'

/**
 * @param accessibleName the Select's visible label or `aria-label`.
 * @param optionLabel the option's visible text.
 */
export async function selectOption(accessibleName: string | RegExp, optionLabel: string | RegExp) {
  const trigger = screen.getByRole('combobox', { name: accessibleName })
  // Enter and Space both open a listbox; Enter is the one a screen-reader
  // user is most likely to reach for.
  fireEvent.keyDown(trigger, { key: 'Enter' })
  const listbox = await screen.findByRole('listbox')
  fireEvent.click(within(listbox).getByRole('option', { name: optionLabel }))
}
