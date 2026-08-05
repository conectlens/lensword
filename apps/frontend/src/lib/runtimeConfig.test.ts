import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetApiBaseForTests, resolveApiBase } from './runtimeConfig'

const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

/** The webview as Tauri leaves it, minus the marker's real contents. */
const webview = window as unknown as Record<string, unknown>

function enterDesktopShell(): void {
  // The marker Tauri injects into the webview; its presence is what the adapter
  // feature-detects on.
  webview.__TAURI_INTERNALS__ = {}
}

afterEach(() => {
  delete webview.__TAURI_INTERNALS__
  invoke.mockReset()
  resetApiBaseForTests()
})

describe('resolveApiBase', () => {
  it('uses the build-time value in the browser and never calls the shell', async () => {
    await expect(resolveApiBase()).resolves.toBe('http://localhost:8000')
    expect(invoke).not.toHaveBeenCalled()
  })

  it('asks the shell for the endpoint when running on the desktop', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue({ base_url: 'https://api.example.com', source: 'config-file' })

    await expect(resolveApiBase()).resolves.toBe('https://api.example.com')
    expect(invoke).toHaveBeenCalledWith('get_api_config')
  })

  it('resolves once and reuses the result', async () => {
    enterDesktopShell()
    invoke.mockResolvedValue({ base_url: 'https://api.example.com', source: 'environment' })

    await Promise.all([resolveApiBase(), resolveApiBase(), resolveApiBase()])

    expect(invoke).toHaveBeenCalledTimes(1)
  })

  it('surfaces a rejected endpoint instead of falling back to the browser default', async () => {
    // The host rejects anything that is not loopback or HTTPS. Swallowing that
    // here would point the desktop app at localhost while the user believes it
    // is talking to the server they configured.
    enterDesktopShell()
    invoke.mockRejectedValue('refusing plain http to remote host `api.example.com`')

    await expect(resolveApiBase()).rejects.toBeTruthy()
  })

  it('does not cache a failure, so a later attempt can succeed', async () => {
    enterDesktopShell()
    invoke.mockRejectedValueOnce('transient')
    await expect(resolveApiBase()).rejects.toBeTruthy()

    invoke.mockResolvedValue({ base_url: 'https://api.example.com', source: 'default' })
    await expect(resolveApiBase()).resolves.toBe('https://api.example.com')
  })
})
