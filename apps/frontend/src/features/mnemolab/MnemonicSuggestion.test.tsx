import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MnemonicSuggestion } from './MnemonicSuggestion'
import { mnemonicsApi } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  mnemonicsApi: { suggest: vi.fn() },
}))

const suggest = vi.mocked(mnemonicsApi.suggest)

function clickSuggest() {
  fireEvent.click(screen.getByRole('button', { name: /suggest with ai/i }))
}

describe('MnemonicSuggestion', () => {
  // Block body on purpose: mockReset() returns the mock itself, and vitest
  // treats a value returned from beforeEach as a teardown callback — an
  // implicit return would have vitest invoke the mock after every test.
  beforeEach(() => {
    suggest.mockReset()
  })

  it('renders the suggestion text when the provider answers', async () => {
    suggest.mockResolvedValue({ status: 'ok', text: "A 'perro' guards the pear tree." })
    render(<MnemonicSuggestion wordId={7} />)

    clickSuggest()

    expect(await screen.findByText("A 'perro' guards the pear tree.")).toBeInTheDocument()
  })

  it('shows a calm notice, not an error, when no provider is configured', async () => {
    suggest.mockResolvedValue({ status: 'disabled' })
    render(<MnemonicSuggestion wordId={7} />)

    clickSuggest()

    expect(await screen.findByText(/ai suggestions unavailable/i)).toBeInTheDocument()
    // "Disabled" is a configuration state, not a fault — no alarming wording
    // and nothing to retry, because retrying cannot change a config value.
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('shows the detail and a retry when the provider is configured but unreachable', async () => {
    suggest.mockResolvedValue({ status: 'unavailable', detail: 'Ollama is not reachable at http://localhost:11434' })
    render(<MnemonicSuggestion wordId={7} />)

    clickSuggest()

    expect(await screen.findByText(/not reachable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('retries the request when the retry control is used', async () => {
    suggest.mockResolvedValueOnce({ status: 'unavailable', detail: 'daemon down' })
    suggest.mockResolvedValueOnce({ status: 'ok', text: 'second time lucky' })
    render(<MnemonicSuggestion wordId={7} />)

    clickSuggest()
    fireEvent.click(await screen.findByRole('button', { name: /try again/i }))

    expect(await screen.findByText('second time lucky')).toBeInTheDocument()
    expect(suggest).toHaveBeenCalledTimes(2)
  })

  it('degrades to a retryable message when the request itself fails', async () => {
    suggest.mockRejectedValue(new Error('Failed to fetch'))
    render(<MnemonicSuggestion wordId={7} />)

    clickSuggest()

    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('does not call the provider until the user asks for a suggestion', async () => {
    suggest.mockResolvedValue({ status: 'disabled' })
    render(<MnemonicSuggestion wordId={7} />)

    await waitFor(() => expect(suggest).not.toHaveBeenCalled())
  })

  it('hands the accepted suggestion to the caller', async () => {
    const onUse = vi.fn()
    suggest.mockResolvedValue({ status: 'ok', text: 'picture a barking pear' })
    render(<MnemonicSuggestion wordId={7} onUse={onUse} />)

    clickSuggest()
    fireEvent.click(await screen.findByRole('button', { name: /use this/i }))

    expect(onUse).toHaveBeenCalledWith('picture a barking pear')
  })

  it('requests a suggestion for the word it was given', async () => {
    suggest.mockResolvedValue({ status: 'ok', text: 'x' })
    render(<MnemonicSuggestion wordId={42} />)

    clickSuggest()

    await waitFor(() => expect(suggest).toHaveBeenCalledWith(42))
  })
})
