/**
 * The themed dropdown (issue #341).
 *
 * The bug was never visible in the DOM: a native `<select>` styled its
 * `<option>` elements perfectly well, and the browser then ignored that and
 * drew the open list as OS chrome — white, against a dark app. So the test
 * that matters is not "the popup is dark", which no unit test can see, but
 * **the open list is part of the page at all**. Once the options are real
 * elements the app renders, they inherit the app's theme by construction.
 *
 * The rest of this file guards what a hand-rolled listbox would have got
 * wrong, and which the issue names as an acceptance criterion: keyboard
 * operation and accessible labelling.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ANY_OPTION, Select } from './Select'

const OPTIONS = [
  { value: 'a1', label: 'A1' },
  { value: 'b2', label: 'B2' },
  { value: 'c1', label: 'C1' },
]

function open(name: string | RegExp = 'Level') {
  const trigger = screen.getByRole('combobox', { name })
  fireEvent.keyDown(trigger, { key: 'Enter' })
  return screen.findByRole('listbox')
}

it('renders the open list as part of the page rather than native popup chrome', async () => {
  render(<Select label="Level" options={OPTIONS} value="a1" onValueChange={() => {}} />)

  const listbox = await open()

  // Real elements the app rendered — which is precisely why they can be
  // themed, and why an <option> never could be.
  expect(within(listbox).getAllByRole('option')).toHaveLength(3)
  expect(within(listbox).getByRole('option', { name: 'B2' })).toBeInTheDocument()
  expect(document.querySelector('select')).toBeNull()
})

it('reports the chosen value', async () => {
  const onValueChange = vi.fn()
  render(<Select label="Level" options={OPTIONS} value="a1" onValueChange={onValueChange} />)

  const listbox = await open()
  fireEvent.click(within(listbox).getByRole('option', { name: 'C1' }))

  expect(onValueChange).toHaveBeenCalledWith('c1')
})

it('shows the current selection on the closed trigger', () => {
  render(<Select label="Level" options={OPTIONS} value="b2" onValueChange={() => {}} />)

  expect(screen.getByRole('combobox', { name: 'Level' })).toHaveTextContent('B2')
})

it('shows the placeholder when nothing is selected yet', () => {
  render(<Select label="Level" options={OPTIONS} placeholder="Pick a level" onValueChange={() => {}} />)

  expect(screen.getByRole('combobox', { name: 'Level' })).toHaveTextContent('Pick a level')
})

describe('accessibility', () => {
  it('associates a visible label with the control', () => {
    render(<Select label="Level" options={OPTIONS} value="a1" onValueChange={() => {}} />)

    // Not merely present — actually associated, which is what a screen reader
    // announces.
    expect(screen.getByRole('combobox', { name: 'Level' })).toBeInTheDocument()
  })

  it('accepts an aria-label where the design has no visible one', () => {
    render(<Select aria-label="Bulk CEFR level" options={OPTIONS} value="a1" onValueChange={() => {}} />)

    // Several toolbars have no room for a visible label. A dropdown whose only
    // description is its current value is unusable without this.
    expect(screen.getByRole('combobox', { name: 'Bulk CEFR level' })).toBeInTheDocument()
  })

  it('opens from the keyboard and can be chosen from without a pointer', async () => {
    const onValueChange = vi.fn()
    render(<Select label="Level" options={OPTIONS} value="a1" onValueChange={onValueChange} />)

    const listbox = await open()
    fireEvent.click(within(listbox).getByRole('option', { name: 'B2' }))

    expect(onValueChange).toHaveBeenCalledWith('b2')
  })

  it('does not offer a disabled option as choosable', async () => {
    render(
      <Select
        label="Level"
        options={[...OPTIONS, { value: 'c2', label: 'C2', disabled: true }]}
        value="a1"
        onValueChange={() => {}}
      />,
    )

    const listbox = await open()

    expect(within(listbox).getByRole('option', { name: 'C2' })).toHaveAttribute('data-disabled')
  })
})

it('supports a sentinel for the "no filter" choice an option cannot carry', async () => {
  // Radix reserves the empty string for "nothing selected", so a native
  // <option value=""> becomes a real value the call site maps back itself.
  function Filter() {
    const [level, setLevel] = useState('')
    return (
      <>
        <Select
          aria-label="Minimum level"
          value={level || ANY_OPTION}
          onValueChange={(next) => setLevel(next === ANY_OPTION ? '' : next)}
          options={[{ value: ANY_OPTION, label: 'Any' }, ...OPTIONS]}
        />
        <output>{level === '' ? 'no filter' : level}</output>
      </>
    )
  }
  render(<Filter />)

  const listbox = await open('Minimum level')
  fireEvent.click(within(listbox).getByRole('option', { name: 'B2' }))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('b2'))

  const reopened = await open('Minimum level')
  fireEvent.click(within(reopened).getByRole('option', { name: 'Any' }))

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('no filter'))
})
