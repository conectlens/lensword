import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AISettingsCard } from './SettingsPage'

const settings = {
  provider: 'ollama' as const,
  model: 'llama3.2',
  base_url: 'http://localhost:11434',
  max_output_tokens: 200,
  context_max_chars: 500,
}

describe('AISettingsCard', () => {
  it('shows a local validation error instead of sending an invalid model', () => {
    const onSave = vi.fn()
    render(<AISettingsCard settings={settings} onSave={onSave} />)

    fireEvent.change(screen.getByLabelText('AI model'), { target: { value: '  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save AI settings' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Model is required.')
    expect(onSave).not.toHaveBeenCalled()
  })

  it('rejects zero output bounds before saving', () => {
    const onSave = vi.fn()
    render(<AISettingsCard settings={settings} onSave={onSave} />)

    fireEvent.change(screen.getByLabelText('Maximum output tokens'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save AI settings' }))

    expect(screen.getByRole('alert')).toHaveTextContent('greater than zero')
    expect(onSave).not.toHaveBeenCalled()
  })
})
