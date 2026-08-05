export interface SelectionCaptureConfig {
  enabled: boolean;
  shortcut: string;
}
export interface SelectionCaptureStatus {
  enabled: boolean;
  shortcut: string;
  platform: string;
  capability: string;
  fallback: string;
  permissionRequired: boolean;
}
export interface SelectionCapture {
  status: string;
  text: string | null;
  kind: "word" | "paragraph" | null;
  sourceApplication: string | null;
}

function desktop(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
async function invoke<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(command, args);
}
export function isSelectionCaptureDesktopAvailable(): boolean {
  return desktop();
}
export async function selectionCaptureStatus(): Promise<SelectionCaptureStatus> {
  return invoke("selection_capture_status");
}
export async function configureSelectionCapture(
  config: SelectionCaptureConfig,
): Promise<void> {
  await invoke("selection_capture_configure", { config });
}
export async function captureSelectedText(): Promise<SelectionCapture> {
  return invoke("selection_capture");
}
