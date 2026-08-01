import { afterEach, describe, expect, it, vi } from 'vitest'

import { connectMcpServer, isMcpDesktopAvailable, listMcpServers, saveMcpServer } from './mcpClient'

const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

const webview = window as unknown as Record<string, unknown>

afterEach(() => {
  delete webview.__TAURI_INTERNALS__
  invoke.mockReset()
})

describe('MCP desktop bridge', () => {
  it('does not expose a browser fallback registry', async () => {
    await expect(listMcpServers()).resolves.toEqual([])
    expect(isMcpDesktopAvailable()).toBe(false)
    expect(invoke).not.toHaveBeenCalled()
  })

  it('uses typed host commands only inside the desktop shell', async () => {
    webview.__TAURI_INTERNALS__ = {}
    invoke.mockResolvedValueOnce(undefined).mockResolvedValueOnce({ id: 'notes', health: 'connected' })
    await saveMcpServer({ id: 'notes', name: 'Notes', command: 'notes-mcp', args: [], enabled: true, workspaceRoots: ['/notes'], allowedTools: ['read_note'], timeoutMs: 1_000, credential: 'not-returned' })
    await expect(connectMcpServer('notes')).resolves.toMatchObject({ health: 'connected' })
    expect(invoke).toHaveBeenNthCalledWith(1, 'mcp_server_save', expect.objectContaining({ server: expect.objectContaining({ credential: 'not-returned' }) }))
    expect(invoke).toHaveBeenLastCalledWith('mcp_server_connect', { serverId: 'notes' })
  })
})
