import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { useTraySync } from './useTraySync'
import { aiSettingsApi, groupsApi, settingsApi } from './api'
import { isDesktopShell } from './desktopNotifications'
import { onTrayAction, setTrayStatus } from './tray'
import type { AISettings, Group, RecallSettings } from './types'

vi.mock('./api', () => ({
  groupsApi: { list: vi.fn() },
  settingsApi: { getRecallSettings: vi.fn(), updateRecallSettings: vi.fn() },
  aiSettingsApi: { get: vi.fn() },
}))
vi.mock('./desktopNotifications', () => ({ isDesktopShell: vi.fn() }))
vi.mock('./tray', () => ({ setTrayStatus: vi.fn(), onTrayAction: vi.fn() }))

const list = vi.mocked(groupsApi.list)
const getRecallSettings = vi.mocked(settingsApi.getRecallSettings)
const updateRecallSettings = vi.mocked(settingsApi.updateRecallSettings)
const aiGet = vi.mocked(aiSettingsApi.get)
const desktopShell = vi.mocked(isDesktopShell)
const trayStatus = vi.mocked(setTrayStatus)
const trayAction = vi.mocked(onTrayAction)

const group = (over: Partial<Group> = {}): Group => ({
  id: 1,
  name: 'Travel',
  target_language: 'Spanish',
  created_at: '2026-08-01T00:00:00',
  word_count: 0,
  mastered_count: 0,
  due_count: 0,
  last_reviewed_at: null,
  ...over,
})

const recall = (over: Partial<RecallSettings> = {}): RecallSettings => ({
  scheduler: 'sm2',
  enabled: true,
  intensity: 3,
  morning_checkin_enabled: true,
  idle_time_enabled: true,
  walking_mode_enabled: false,
  walking_steps_threshold: 1000,
  study_breaks_enabled: true,
  study_blocks_before_break: 2,
  night_winddown_enabled: false,
  night_start_time: '22:00',
  night_end_time: '23:00',
  push_enabled: true,
  email_enabled: false,
  desktop_enabled: false,
  in_app_enabled: true,
  quiet_hours_start: null,
  quiet_hours_end: null,
  notifications_paused: false,
  semantic_relatedness_enabled: false,
  learning_diagnosis_enabled: false,
  acquisition_loop_enabled: false,
  ai_coach_enabled: false,
  ai_companion_enabled: false,
  time_zone: 'UTC',
  ...over,
})

const aiSettings = (over: Partial<AISettings> = {}): AISettings => ({
  provider: 'ollama',
  model: 'llama3.2',
  base_url: 'http://localhost:11434',
  max_output_tokens: 512,
  context_max_chars: 4000,
  ...over,
})

beforeEach(() => {
  list.mockReset()
  getRecallSettings.mockReset()
  updateRecallSettings.mockReset()
  aiGet.mockReset()
  desktopShell.mockReset()
  trayStatus.mockReset()
  trayAction.mockReset()

  list.mockResolvedValue([])
  getRecallSettings.mockResolvedValue(recall())
  trayAction.mockResolvedValue(vi.fn())
})

describe('useTraySync', () => {
  it('does nothing outside a desktop shell', () => {
    desktopShell.mockReturnValue(false)

    renderHook(() => useTraySync({ enabled: true, isAdmin: false, navigate: vi.fn() }))

    expect(trayStatus).not.toHaveBeenCalled()
    expect(trayAction).not.toHaveBeenCalled()
  })

  it('does nothing while signed out, even inside the desktop shell', () => {
    desktopShell.mockReturnValue(true)

    renderHook(() => useTraySync({ enabled: false, isAdmin: false, navigate: vi.fn() }))

    expect(trayStatus).not.toHaveBeenCalled()
    expect(trayAction).not.toHaveBeenCalled()
  })

  it('pushes the real due count and pause state on mount', async () => {
    desktopShell.mockReturnValue(true)
    list.mockResolvedValue([group({ id: 1, due_count: 3 }), group({ id: 2, due_count: 2 })])
    getRecallSettings.mockResolvedValue(recall({ notifications_paused: true }))

    renderHook(() => useTraySync({ enabled: true, isAdmin: false, navigate: vi.fn() }))

    await waitFor(() =>
      expect(trayStatus).toHaveBeenCalledWith(
        expect.objectContaining({ dueCount: 5, notificationsPaused: true }),
      ),
    )
  })

  it('includes the AI provider for an admin session', async () => {
    desktopShell.mockReturnValue(true)
    aiGet.mockResolvedValue(aiSettings({ provider: 'ollama', model: 'llama3.2' }))

    renderHook(() => useTraySync({ enabled: true, isAdmin: true, navigate: vi.fn() }))

    await waitFor(() =>
      expect(trayStatus).toHaveBeenCalledWith(expect.objectContaining({ aiProvider: 'Ollama (llama3.2)' })),
    )
  })

  it('never asks the admin-only endpoint for a non-admin session', async () => {
    // GET /api/v1/ai-settings is admin-only; calling it as a learner would
    // only ever produce a 403 to swallow.
    desktopShell.mockReturnValue(true)

    renderHook(() => useTraySync({ enabled: true, isAdmin: false, navigate: vi.fn() }))

    await waitFor(() =>
      expect(trayStatus).toHaveBeenCalledWith(expect.objectContaining({ aiProvider: null })),
    )
    expect(aiGet).not.toHaveBeenCalled()
  })

  it('never claims the local model is ready or unavailable without checking', async () => {
    // Confirming reachability means a real request to the Ollama host; a
    // tray tooltip refresh has no business making one every 30s.
    desktopShell.mockReturnValue(true)
    aiGet.mockResolvedValue(aiSettings())

    renderHook(() => useTraySync({ enabled: true, isAdmin: true, navigate: vi.fn() }))

    await waitFor(() =>
      expect(trayStatus).toHaveBeenCalledWith(expect.objectContaining({ localModelReady: null })),
    )
  })

  it('wires the caller-supplied navigate function straight through', async () => {
    desktopShell.mockReturnValue(true)
    const navigate = vi.fn()

    renderHook(() => useTraySync({ enabled: true, isAdmin: false, navigate }))

    await waitFor(() =>
      expect(trayAction).toHaveBeenCalledWith(expect.objectContaining({ navigate })),
    )
  })

  it('flips the pause flag and re-syncs when the tray asks to toggle pause', async () => {
    desktopShell.mockReturnValue(true)
    let handlers: { togglePause: () => void | Promise<void> } | undefined
    trayAction.mockImplementation(async (h) => {
      handlers = h
      return () => {}
    })
    getRecallSettings.mockResolvedValue(recall({ notifications_paused: false }))
    updateRecallSettings.mockResolvedValue(recall({ notifications_paused: true }))

    renderHook(() => useTraySync({ enabled: true, isAdmin: false, navigate: vi.fn() }))
    await waitFor(() => expect(handlers).toBeDefined())

    await act(async () => {
      await handlers!.togglePause()
    })

    expect(updateRecallSettings).toHaveBeenCalledWith(
      expect.objectContaining({ notifications_paused: true }),
    )
  })

  it('unsubscribes from tray actions on unmount', async () => {
    desktopShell.mockReturnValue(true)
    const unsubscribe = vi.fn()
    trayAction.mockResolvedValue(unsubscribe)

    const { unmount } = renderHook(() => useTraySync({ enabled: true, isAdmin: false, navigate: vi.fn() }))
    await waitFor(() => expect(trayAction).toHaveBeenCalled())

    unmount()

    await waitFor(() => expect(unsubscribe).toHaveBeenCalled())
  })
})
