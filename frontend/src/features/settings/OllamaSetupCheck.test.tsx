import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { OllamaSetupCheck } from './OllamaSetupCheck'
import { aiSettingsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  aiSettingsApi: { probe: vi.fn() },
}))

const probe = vi.mocked(aiSettingsApi.probe)

const base = {
  reachable: true,
  ready: false,
  models: [] as string[],
  configured_model: 'llama3.2',
  configured_model_installed: false,
  recommended_model: 'llama3.2',
  detail: '',
}

beforeEach(() => {
  probe.mockReset()
})

async function runCheck() {
  render(<OllamaSetupCheck />)
  fireEvent.click(screen.getByRole('button', { name: 'Check Ollama' }))
  return screen.findByRole('status')
}

describe('OllamaSetupCheck', () => {
  it('shows the reason the server gave rather than composing its own', async () => {
    // A UI that reconstructed the message from a boolean would drift out of
    // agreement with what was actually observed.
    probe.mockResolvedValue({
      ...base,
      reachable: false,
      detail: 'Nothing is answering at http://localhost:11434.',
    })

    expect(await runCheck()).toHaveTextContent('Nothing is answering at http://localhost:11434.')
  })

  it('suggests a pull when the daemon is running with nothing installed', async () => {
    probe.mockResolvedValue({
      ...base,
      detail: 'Ollama is running, but no models are installed.',
    })

    expect(await runCheck()).toHaveTextContent('ollama pull llama3.2')
  })

  it('does not suggest a pull when models are already installed', async () => {
    // Telling someone with models to pull one is noise.
    probe.mockResolvedValue({
      ...base,
      models: ['mistral'],
      detail: 'Ollama is running, but `llama3.2` is not installed.',
    })

    const status = await runCheck()
    expect(status).not.toHaveTextContent('ollama pull llama3.2')
    expect(status).toHaveTextContent('Installed: mistral')
  })

  it('distinguishes running-but-unusable from not running', async () => {
    // They need completely different fixes, so they must not look the same.
    probe.mockResolvedValue({ ...base, reachable: true, ready: false, detail: 'partial' })
    const partial = render(<OllamaSetupCheck />)
    fireEvent.click(screen.getByRole('button', { name: 'Check Ollama' }))
    const partialClass = (await screen.findByRole('status')).className
    partial.unmount()

    probe.mockResolvedValue({ ...base, reachable: false, ready: false, detail: 'down' })
    render(<OllamaSetupCheck />)
    fireEvent.click(screen.getByRole('button', { name: 'Check Ollama' }))
    const downClass = (await screen.findByRole('status')).className

    expect(partialClass).not.toEqual(downClass)
  })

  it('reports a failed check instead of appearing to have found nothing', async () => {
    probe.mockRejectedValue(new Error('offline'))

    render(<OllamaSetupCheck />)
    fireEvent.click(screen.getByRole('button', { name: 'Check Ollama' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not run the check')
  })

  it('shows nothing until the check is run', () => {
    render(<OllamaSetupCheck />)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(probe).not.toHaveBeenCalled()
  })
})
