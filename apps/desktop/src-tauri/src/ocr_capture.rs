//! Screen-region capture and OCR, gated behind an explicit review step
//! (issue #84).
//!
//! A dedicated OCR engine reads the pixels — never a general LLM, which
//! would be asked to "read" an image it cannot actually see character
//! positions in and would silently fabricate plausible-looking text instead
//! of failing.
//!
//! Implemented for macOS only today, in the `macos` submodule below: it
//! shells out to the system `screencapture` tool for both the
//! region-selection UI and the capture itself (it already owns Screen
//! Recording permission handling), the same way `selection_capture.rs`
//! already shells out to `osascript` — a narrow, specific Tauri command, not
//! a general shell capability exposed to the frontend (ADR 0001). Windows
//! and Linux have no equivalent single built-in tool and report
//! `unsupported` rather than a half-implemented capture path; see issue
//! #84's follow-up for what each needs.
//!
//! The OCR engine (`ocrs`, pure Rust, no system library dependency) and its
//! model files are scoped as a macOS-only dependency in Cargo.toml, and
//! every function that touches them lives inside `mod macos` here — compiled
//! only where it can be reached, since compiling it everywhere but reaching
//! it from nowhere on Linux or Windows would be dead code, and `-D warnings`
//! denies that.
use serde::Serialize;
use tauri::AppHandle;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ScreenCaptureStatus {
    pub platform: &'static str,
    // "native" today only on macOS. "unsupported" elsewhere is honest about
    // the actual state rather than a placeholder that looks implemented.
    pub capability: &'static str,
    pub permission_required: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BoundingBox {
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OcrLine {
    pub text: String,
    pub bounding_box: BoundingBox,
    // `ocrs` does not report a per-line confidence score today (only an
    // internal detection threshold that decides whether a line is returned
    // at all) — `None` here is that honest limitation, not a bug. The
    // review UI should treat `None` the same as a genuinely low score:
    // flagged, never silently trusted.
    pub confidence: Option<f32>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OcrCaptureResult {
    // "ok" | "cancelled" | "permission_required" | "unsupported" | "engine_unavailable" | "empty"
    pub status: String,
    pub lines: Vec<OcrLine>,
    pub detail: Option<String>,
}

const fn platform() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}

const fn capability() -> (&'static str, bool) {
    if cfg!(target_os = "macos") {
        ("native", true)
    } else {
        ("unsupported", false)
    }
}

#[tauri::command]
pub fn screen_capture_status() -> ScreenCaptureStatus {
    let (capability, permission_required) = capability();
    ScreenCaptureStatus {
        platform: platform(),
        capability,
        permission_required,
    }
}

#[tauri::command]
pub fn capture_screen_region_and_ocr(app: AppHandle) -> Result<OcrCaptureResult, String> {
    let (capability, _) = capability();
    if capability != "native" {
        // Referenced on every platform so the parameter is never simply
        // unused where the branch below is compiled out.
        let _ = &app;
        return Ok(OcrCaptureResult {
            status: "unsupported".into(),
            lines: vec![],
            detail: Some(format!(
                "screen capture is not yet implemented on {}",
                platform()
            )),
        });
    }

    #[cfg(target_os = "macos")]
    {
        Ok(macos::capture_and_ocr(&app))
    }
    #[cfg(not(target_os = "macos"))]
    {
        unreachable!("capability() already returned early for every non-macOS target")
    }
}

#[cfg(target_os = "macos")]
mod macos {
    use std::path::{Path, PathBuf};
    use std::process::Command;
    use std::sync::OnceLock;
    use std::time::{SystemTime, UNIX_EPOCH};

    use ocrs::{ImageSource, OcrEngine as Engine, OcrEngineParams};
    use rten::Model;
    use rten_imageproc::RotatedRect;
    use tauri::{AppHandle, Manager};

    use super::{BoundingBox, OcrCaptureResult, OcrLine};

    const DETECTION_MODEL_RESOURCE: &str = "resources/ocr-models/text-detection.rten";
    const RECOGNITION_MODEL_RESOURCE: &str = "resources/ocr-models/text-recognition.rten";

    /// The whole capture -> OCR -> cleanup flow, already reduced to a
    /// result the frontend can render directly — nothing left for the
    /// caller to decide.
    pub fn capture_and_ocr(app: &AppHandle) -> OcrCaptureResult {
        let path = temp_capture_path();
        match capture_region_to(&path) {
            Ok(true) => {}
            Ok(false) => {
                return OcrCaptureResult {
                    status: "cancelled".into(),
                    lines: vec![],
                    detail: None,
                };
            }
            Err(detail) => {
                return OcrCaptureResult {
                    status: "permission_required".into(),
                    lines: vec![],
                    detail: Some(detail),
                };
            }
        }

        let outcome = match ocr_image_file(app, &path) {
            Ok(lines) if lines.is_empty() => OcrCaptureResult {
                status: "empty".into(),
                lines,
                detail: None,
            },
            Ok(lines) => OcrCaptureResult {
                status: "ok".into(),
                lines,
                detail: None,
            },
            Err(detail) => OcrCaptureResult {
                status: "engine_unavailable".into(),
                lines: vec![],
                detail: Some(detail),
            },
        };
        // Always attempted, regardless of the outcome above: a temp file is
        // never left behind for the user to have to notice and clean up
        // themselves, and nothing here ever offers a way to keep it.
        let _ = std::fs::remove_file(&path);
        outcome
    }

    fn temp_capture_path() -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        std::env::temp_dir().join(format!("lensword-ocr-capture-{stamp}.png"))
    }

    /// Loaded once per process and reused: the two models together are
    /// ~12MB, and loading them is measured in the hundreds of milliseconds
    /// — worth paying once, not on every capture.
    static OCR_ENGINE: OnceLock<Result<Engine, String>> = OnceLock::new();

    fn ocr_engine(app: &AppHandle) -> Result<&Engine, String> {
        OCR_ENGINE
            .get_or_init(|| load_engine(app))
            .as_ref()
            .map_err(Clone::clone)
    }

    fn load_engine(app: &AppHandle) -> Result<Engine, String> {
        let resolve = |resource: &str| -> Result<PathBuf, String> {
            app.path()
                .resolve(resource, tauri::path::BaseDirectory::Resource)
                .map_err(|_| format!("could not locate bundled resource '{resource}'"))
        };
        let detection_path = resolve(DETECTION_MODEL_RESOURCE)?;
        let recognition_path = resolve(RECOGNITION_MODEL_RESOURCE)?;

        let detection_model = Model::load_file(&detection_path)
            .map_err(|e| format!("failed to load OCR detection model: {e}"))?;
        let recognition_model = Model::load_file(&recognition_path)
            .map_err(|e| format!("failed to load OCR recognition model: {e}"))?;

        Engine::new(OcrEngineParams {
            detection_model: Some(detection_model),
            recognition_model: Some(recognition_model),
            ..Default::default()
        })
        .map_err(|e| format!("failed to construct OCR engine: {e}"))
    }

    /// Reads and OCRs an already-captured image, without touching the
    /// filesystem beyond the read — split out from `capture_and_ocr` so the
    /// OCR half is independently exercisable against a fixture image.
    fn ocr_image_file(app: &AppHandle, path: &Path) -> Result<Vec<OcrLine>, String> {
        let engine = ocr_engine(app)?;

        let img = image::open(path)
            .map_err(|e| format!("could not read captured image: {e}"))?
            .into_rgb8();
        let source = ImageSource::from_bytes(img.as_raw(), img.dimensions())
            .map_err(|e| format!("could not prepare captured image: {e}"))?;
        let input = engine
            .prepare_input(source)
            .map_err(|e| format!("could not prepare OCR input: {e}"))?;

        let word_rects = engine
            .detect_words(&input)
            .map_err(|e| format!("text detection failed: {e}"))?;
        let line_rects = engine.find_text_lines(&input, &word_rects);
        let line_texts = engine
            .recognize_text(&input, &line_rects)
            .map_err(|e| format!("text recognition failed: {e}"))?;

        Ok(line_texts
            .iter()
            .zip(line_rects.iter())
            .filter_map(|(text, rect)| {
                let text = text.as_ref()?;
                let text_str = text.to_string();
                if text_str.trim().is_empty() {
                    return None;
                }
                Some(OcrLine {
                    text: text_str,
                    bounding_box: bounding_box(rect),
                    confidence: None,
                })
            })
            .collect())
    }

    fn bounding_box(rects: &[RotatedRect]) -> BoundingBox {
        // RotatedRect's bounding rect is float-coordinate (it comes from
        // possibly-rotated corners); rounded to whole pixels here since
        // nothing downstream needs sub-pixel precision for a
        // review-preview box.
        let rect = rten_imageproc::bounding_rect(rects.iter())
            .unwrap_or(rten_imageproc::Rect::from_tlhw(0.0, 0.0, 0.0, 0.0));
        BoundingBox {
            left: rect.left().round() as i32,
            top: rect.top().round() as i32,
            right: rect.right().round() as i32,
            bottom: rect.bottom().round() as i32,
        }
    }

    fn capture_region_to(path: &Path) -> Result<bool, String> {
        // `-i` is the interactive, drag-to-select region UI macOS already
        // ships (the same one Cmd+Shift+4 opens) — it owns the Screen
        // Recording permission prompt itself, so nothing here has to ask
        // separately. `-x` suppresses the capture sound.
        let status = Command::new("screencapture")
            .args(["-i", "-x"])
            .arg(path)
            .status()
            .map_err(|e| format!("could not launch screencapture: {e}"))?;
        // A cancelled selection (Escape) exits successfully but writes no
        // file — distinguished from a real failure by checking for the
        // file rather than the exit code alone.
        Ok(status.success() && path.exists())
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn temp_paths_are_unique_and_scoped_to_this_app() {
            let a = temp_capture_path();
            let b = temp_capture_path();
            assert_ne!(a, b);
            assert!(a.starts_with(std::env::temp_dir()));
            assert!(a.to_string_lossy().contains("lensword-ocr-capture-"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn macos_reports_native_capability() {
        let (capability, permission_required) = capability();
        if cfg!(target_os = "macos") {
            assert_eq!(capability, "native");
            assert!(permission_required);
        } else {
            assert_eq!(capability, "unsupported");
            assert!(!permission_required);
        }
    }
}
