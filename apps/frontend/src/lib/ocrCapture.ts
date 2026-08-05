export interface ScreenCaptureStatus {
  platform: string;
  capability: string;
  permissionRequired: boolean;
}

export interface OcrBoundingBox {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface OcrLine {
  text: string;
  boundingBox: OcrBoundingBox;
  // Absent rather than a fabricated number: the bundled OCR engine does not
  // report a per-line confidence score. Every line is treated as needing a
  // look, not just the ones a score would flag (issue #84).
  confidence: number | null;
}

export interface OcrCaptureResult {
  status:
    | "ok"
    | "cancelled"
    | "permission_required"
    | "unsupported"
    | "engine_unavailable"
    | "empty";
  lines: OcrLine[];
  detail: string | null;
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

export function isScreenCaptureDesktopAvailable(): boolean {
  return desktop();
}

export async function screenCaptureStatus(): Promise<ScreenCaptureStatus> {
  return invoke("screen_capture_status");
}

export async function captureScreenRegionAndOcr(): Promise<OcrCaptureResult> {
  return invoke("capture_screen_region_and_ocr");
}
