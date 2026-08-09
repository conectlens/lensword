/**
 * A dropdown the app draws itself (issue #341).
 *
 * This wrapped a native `<select>` and styled its `<option>` elements. That
 * styling is very largely ignored: browsers render the open dropdown as
 * OS-level chrome, so against this app's dark surface the popup still opened
 * white. No amount of CSS on `<option>` fixes it, because the popup is not
 * part of the page.
 *
 * The open list is therefore rendered as ordinary markup. Radix's Select is
 * the primitive rather than a hand-rolled listbox because the parts that are
 * easy to get wrong are the ones nobody notices until someone depends on
 * them: roving focus, typeahead, `aria-activedescendant`, returning focus to
 * the trigger on close, and not trapping a screen reader inside a div that
 * merely looks like a listbox. It is unstyled, so every visual decision here
 * is still this app's own.
 *
 * Safe in the desktop shell: Radix positions the popup with inline styles,
 * and `apps/desktop/tauri.conf.json` sets `style-src 'self' 'unsafe-inline'`.
 * Worth stating because a CSP block is exactly how the icon font broke in the
 * desktop build before (see `index.html`) — the same class of failure, caught
 * this time by reading the policy rather than by a bug report.
 *
 * The API is `value`/`onValueChange` rather than a native change event.
 * Reading `event.target.value` off something that is no longer an
 * `HTMLSelectElement` would be a lie the types would have to be talked out of.
 */

import { Fragment } from 'react'

import * as RadixSelect from '@radix-ui/react-select'

import { Icon } from './Icon'

export interface SelectOption {
  /**
   * Must not be the empty string. Radix reserves `""` to mean "nothing is
   * selected", which is what shows the placeholder — an option carrying it
   * would be unselectable. A native `<option value="">Any</option>` therefore
   * becomes an option with a real sentinel value, which the call site maps
   * back to "no filter" itself. See `ANY_OPTION` below.
   */
  value: string
  label: string
  disabled?: boolean
}

/** The sentinel for a "no filter / leave unchanged" choice, since an option
 *  cannot carry the empty string. Shared so the several filters that need one
 *  cannot drift onto different magic strings. */
export const ANY_OPTION = '__any__'

/** `md` is the standalone form field; `sm` is the compact control that sits
 *  inline beside its own text, which several toolbars and filters need. */
export type SelectSize = 'sm' | 'md'

const triggerSizes: Record<SelectSize, string> = {
  sm: 'h-9 gap-1.5 px-3 text-sm',
  md: 'h-12 gap-2 px-4 text-base',
}

export interface SelectProps {
  options: SelectOption[]
  value?: string
  onValueChange?: (value: string) => void
  label?: string
  size?: SelectSize
  placeholder?: string
  name?: string
  id?: string
  disabled?: boolean
  required?: boolean
  className?: string
  /** Labels the trigger when there is no visible `label` — a dropdown whose
   *  only description is its current value is unusable with a screen reader. */
  'aria-label'?: string
}

export function Select({
  options,
  value,
  onValueChange,
  label,
  size = 'md',
  placeholder = 'Select…',
  name,
  id,
  disabled,
  required,
  className = '',
  'aria-label': ariaLabel,
}: SelectProps) {
  const selectId = id ?? name
  // Only wraps when there is a label to stack above the control. An inline
  // dropdown sitting beside its own text must not be forced into a block.
  const Wrapper = label ? 'div' : Fragment
  const wrapperProps = label ? { className: 'flex flex-col gap-2' } : {}
  return (
    <Wrapper {...wrapperProps}>
      {label && (
        <label htmlFor={selectId} className="text-sm font-medium text-white">
          {label}
        </label>
      )}
      <RadixSelect.Root
        value={value}
        onValueChange={onValueChange}
        name={name}
        disabled={disabled}
        required={required}
      >
        <RadixSelect.Trigger
          id={selectId}
          aria-label={ariaLabel ?? label}
          className={`inline-flex items-center justify-between rounded-lg border border-white/10 bg-white/5 text-left text-white focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50 ${triggerSizes[size]} ${label ? 'w-full' : ''} ${className}`}
        >
          {/* Radix renders the placeholder only while the value is empty. */}
          <RadixSelect.Value placeholder={<span className="text-white/40">{placeholder}</span>} />
          <RadixSelect.Icon asChild>
            <Icon name="expand_more" className="shrink-0 text-white/40" />
          </RadixSelect.Icon>
        </RadixSelect.Trigger>

        <RadixSelect.Portal>
          <RadixSelect.Content
            // Positioned rather than in-flow so a dropdown near the bottom of
            // a page opens upward instead of off-screen.
            position="popper"
            sideOffset={4}
            className="z-50 max-h-64 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-white/10 bg-surface shadow-soft"
          >
            <RadixSelect.Viewport className="p-1">
              {options.map((option) => (
                <RadixSelect.Item
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                  className="flex cursor-pointer select-none items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-white outline-none data-[disabled]:cursor-not-allowed data-[highlighted]:bg-white/10 data-[disabled]:opacity-40"
                >
                  <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                  <RadixSelect.ItemIndicator asChild>
                    <Icon name="check" className="text-primary" />
                  </RadixSelect.ItemIndicator>
                </RadixSelect.Item>
              ))}
            </RadixSelect.Viewport>
          </RadixSelect.Content>
        </RadixSelect.Portal>
      </RadixSelect.Root>
    </Wrapper>
  )
}
