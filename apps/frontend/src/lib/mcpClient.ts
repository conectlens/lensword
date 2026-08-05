/** Typed, redacted bridge to the desktop-owned MCP registry.
 *
 * Definitions and credentials are deliberately never kept in browser storage.
 * This module returns an empty registry in the web deployment so the settings
 * page can be shared by both targets without exposing a fallback transport.
 */

export interface McpTool {
  name: string
  description: string | null
  schemaFingerprint: string
}

export interface McpServer {
  id: string
  name: string
  enabled: boolean
  workspaceRoots: string[]
  allowedTools: string[]
  health: 'connected' | 'disconnected' | 'disabled'
  identity: string | null
  tools: McpTool[]
  capabilityFingerprint: string | null
  capabilityChanged: boolean
}

export interface McpServerSave {
  id: string
  name: string
  command: string
  args: string[]
  enabled: boolean
  workspaceRoots: string[]
  allowedTools: string[]
  timeoutMs: number
  /** Sent directly to the native host; never returned or persisted by the webview. */
  credential?: string
}

function isDesktopShell(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

async function nativeInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}

export async function listMcpServers(): Promise<McpServer[]> {
  return isDesktopShell() ? nativeInvoke<McpServer[]>('mcp_server_list') : []
}

export async function saveMcpServer(server: McpServerSave): Promise<void> {
  if (!isDesktopShell()) throw new Error('MCP connections are available only in the LensWord desktop app.')
  await nativeInvoke('mcp_server_save', { server })
}

export async function connectMcpServer(serverId: string): Promise<McpServer> {
  if (!isDesktopShell()) throw new Error('MCP connections are available only in the LensWord desktop app.')
  return nativeInvoke<McpServer>('mcp_server_connect', { serverId })
}

export async function disconnectMcpServer(serverId: string): Promise<void> {
  if (!isDesktopShell()) return
  await nativeInvoke('mcp_server_disconnect', { serverId })
}

export async function deleteMcpServer(serverId: string): Promise<void> {
  if (!isDesktopShell()) return
  await nativeInvoke('mcp_server_delete', { serverId })
}

export function isMcpDesktopAvailable(): boolean {
  return isDesktopShell()
}
