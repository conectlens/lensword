/**
 * Feedback on the weekly report's two actions (issue #344).
 *
 * Both buttons used to call `reportsApi.…().then(setReport)` straight from
 * `onClick`: no loading state, no disabled state, no `.catch`. Pressing one
 * gave no visible change until the result arrived, and a failure produced an
 * unhandled promise rejection with nothing shown at all.
 *
 * The distinction worth pinning is between the two error paths. The page
 * already replaces itself with an alert when the *report* cannot be loaded,
 * which is right. Doing that when a *button* fails would throw away the
 * report the user is reading because a follow-up request timed out — a worse
 * outcome than the failure being reported.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

const getWeekly = vi.fn()
const buildWeekly = vi.fn()
const generateNarration = vi.fn()

vi.mock('../../lib/api', () => ({
  reportsApi: {
    getWeekly: (id: number) => getWeekly(id),
    buildWeekly: () => buildWeekly(),
    generateNarration: (id: number) => generateNarration(id),
  },
}))

vi.mock('react-router-dom', () => ({ useParams: () => ({}) }))

const { WeeklyReportPage } = await import('./WeeklyReportPage')

function report(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    narration: null,
    snapshot: {
      week: { start: '2026-08-03', end: '2026-08-09', time_zone: 'UTC' },
      studied: 12,
      retained: 9,
      overdue: 3,
      data_completeness: { warnings: [] },
      difficult_topics: [],
      productive_time_windows: [],
      source_range: { attempt_count: 40, session_count: 5 },
    },
    ...overrides,
  }
}

/** A promise this test resolves or rejects by hand, so the in-flight state is
 *  observable rather than raced against. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  getWeekly.mockReset()
  buildWeekly.mockReset()
  generateNarration.mockReset()
  buildWeekly.mockResolvedValue(report())
})

async function renderLoaded() {
  render(<WeeklyReportPage />)
  return screen.findByRole('button', { name: /generate ai interpretation/i })
}

it('disables both buttons while a request is in flight', async () => {
  const pendingNarration = deferred<ReturnType<typeof report>>()
  generateNarration.mockReturnValue(pendingNarration.promise)
  const generate = await renderLoaded()
  const refresh = screen.getByRole('button', { name: /refresh factual snapshot/i })

  fireEvent.click(generate)

  // Both, not just the one clicked: each replaces the whole report, so letting
  // them race would leave whichever finished last silently winning.
  await waitFor(() => expect(generate).toBeDisabled())
  expect(refresh).toBeDisabled()

  pendingNarration.resolve(report({ narration: 'You studied consistently.' }))
  await waitFor(() => expect(generate).toBeEnabled())
})

it('shows the generated interpretation once the request finishes', async () => {
  generateNarration.mockResolvedValue(report({ narration: 'You studied consistently.' }))
  const generate = await renderLoaded()

  fireEvent.click(generate)

  expect(await screen.findByText('You studied consistently.')).toBeInTheDocument()
})

it('surfaces a failed interpretation instead of failing silently', async () => {
  generateNarration.mockRejectedValue(new Error('The AI provider is unavailable.'))
  const generate = await renderLoaded()

  fireEvent.click(generate)

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('The AI provider is unavailable.')
})

it('keeps the report on screen when an action fails', async () => {
  generateNarration.mockRejectedValue(new Error('The AI provider is unavailable.'))
  const generate = await renderLoaded()

  fireEvent.click(generate)
  await screen.findByRole('alert')

  // The report is still readable — the alert is inline, not a replacement for
  // the page.
  expect(screen.getByRole('heading', { name: /weekly learning report/i })).toBeInTheDocument()
  expect(generate).toBeEnabled()
})

it('applies the same treatment to the neighbouring refresh button', async () => {
  const generate = await renderLoaded()
  const refresh = screen.getByRole('button', { name: /refresh factual snapshot/i })
  buildWeekly.mockRejectedValueOnce(new Error('Could not rebuild the snapshot.'))

  fireEvent.click(refresh)

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not rebuild the snapshot.')
  expect(generate).toBeEnabled()
})

it('clears a previous failure when the action is retried', async () => {
  generateNarration.mockRejectedValueOnce(new Error('The AI provider is unavailable.'))
  const generate = await renderLoaded()

  fireEvent.click(generate)
  await screen.findByRole('alert')

  generateNarration.mockResolvedValue(report({ narration: 'You studied consistently.' }))
  fireEvent.click(generate)

  // A stale error left beside a fresh success would be its own bug.
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(screen.getByText('You studied consistently.')).toBeInTheDocument()
})
