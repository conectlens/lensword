export interface ClipboardConfig { enabled: boolean; paused: boolean; blockedApps: string[] }
export interface ClipboardCapture { status: string; text: string | null; kind: 'word' | 'paragraph' | null }
function desktop(): boolean { return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window }
async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> { const { invoke } = await import('@tauri-apps/api/core'); return invoke<T>(command, args) }
export async function clipboardStatus(): Promise<ClipboardConfig> { return desktop() ? invoke<ClipboardConfig>('clipboard_status') : { enabled: false, paused: false, blockedApps: [] } }
export async function configureClipboard(config: ClipboardConfig): Promise<void> { if (!desktop()) throw new Error('Clipboard capture is available only in the desktop app.'); await invoke('clipboard_configure', { config }) }
export async function captureClipboard(): Promise<ClipboardCapture> { if (!desktop()) return { status: 'unavailable', text: null, kind: null }; return invoke<ClipboardCapture>('clipboard_capture') }
export function isClipboardDesktopAvailable(): boolean { return desktop() }
