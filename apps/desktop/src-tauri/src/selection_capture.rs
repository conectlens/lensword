//! Global selected-text capture with an explicit, privacy-preserving fallback.
//!
//! A platform shortcut only asks the frontend to request a capture. Text stays
//! in process and is returned as a transient candidate; this module never
//! writes selected text to disk or emits it in an event payload.
use crate::clipboard;
use serde::{Deserialize, Serialize};
#[cfg(target_os = "macos")]
use std::process::Command;
use std::{str::FromStr, sync::Mutex};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelectionCaptureConfig {
    pub enabled: bool,
    pub shortcut: String,
}

impl Default for SelectionCaptureConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            shortcut: default_shortcut().into(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelectionCaptureStatus {
    pub enabled: bool,
    pub shortcut: String,
    pub platform: &'static str,
    pub capability: &'static str,
    pub fallback: &'static str,
    pub permission_required: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SelectionCapture {
    pub status: String,
    pub text: Option<String>,
    pub kind: Option<String>,
    pub source_application: Option<String>,
}

pub struct SelectionCaptureState(Mutex<SelectionCaptureConfig>);
impl Default for SelectionCaptureState {
    fn default() -> Self {
        Self(Mutex::new(SelectionCaptureConfig::default()))
    }
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
const fn default_shortcut() -> &'static str {
    if cfg!(target_os = "macos") {
        "Command+Shift+L"
    } else if cfg!(target_os = "windows") {
        "Ctrl+Shift+L"
    } else {
        "Ctrl+Alt+L"
    }
}
fn capability() -> (&'static str, &'static str, bool) {
    if cfg!(target_os = "macos") {
        ("accessibility", "clipboard_or_manual_entry", true)
    } else if cfg!(target_os = "windows") {
        ("clipboard_fallback", "clipboard_or_manual_entry", false)
    } else {
        // Wayland compositors deliberately do not expose global selection APIs.
        ("unsupported_compositor", "clipboard_or_manual_entry", false)
    }
}

fn shortcut(value: &str) -> Result<Shortcut, String> {
    if value.trim().is_empty() {
        return Err("shortcut cannot be empty".into());
    }
    Shortcut::from_str(value)
        .map_err(|_| "invalid shortcut; use a modifier plus a key, for example Ctrl+Shift+L".into())
}

pub fn install(app: &AppHandle) -> Result<(), String> {
    let config = app
        .state::<SelectionCaptureState>()
        .0
        .lock()
        .map_err(|_| "selection capture state unavailable")?
        .clone();
    if config.enabled {
        register(app, &config.shortcut)?;
    }
    Ok(())
}
fn register(app: &AppHandle, value: &str) -> Result<(), String> {
    let shortcut = shortcut(value)?;
    app.global_shortcut()
        .register(shortcut)
        .map_err(|_| "shortcut_conflict".into())
}

#[tauri::command]
pub fn selection_capture_status(
    state: State<'_, SelectionCaptureState>,
) -> Result<SelectionCaptureStatus, String> {
    let config = state
        .0
        .lock()
        .map_err(|_| "selection capture state unavailable")?
        .clone();
    let (capability, fallback, permission_required) = capability();
    Ok(SelectionCaptureStatus {
        enabled: config.enabled,
        shortcut: config.shortcut,
        platform: platform(),
        capability,
        fallback,
        permission_required,
    })
}

#[tauri::command]
pub fn selection_capture_configure(
    app: AppHandle,
    config: SelectionCaptureConfig,
    state: State<'_, SelectionCaptureState>,
) -> Result<(), String> {
    shortcut(&config.shortcut)?;
    let previous = state
        .0
        .lock()
        .map_err(|_| "selection capture state unavailable")?
        .clone();
    let manager = app.global_shortcut();
    manager
        .unregister_all()
        .map_err(|_| "could not update global shortcut")?;
    if config.enabled {
        if let Err(error) = register(&app, &config.shortcut) {
            // A conflicting reassignment must not silently leave the user
            // without their working shortcut.
            if previous.enabled {
                let _ = register(&app, &previous.shortcut);
            }
            return Err(error);
        }
    }
    *state
        .0
        .lock()
        .map_err(|_| "selection capture state unavailable")? = config;
    Ok(())
}

#[tauri::command]
pub fn selection_capture(
    state: State<'_, SelectionCaptureState>,
) -> Result<SelectionCapture, String> {
    if !state
        .0
        .lock()
        .map_err(|_| "selection capture state unavailable")?
        .enabled
    {
        return Ok(SelectionCapture {
            status: "disabled".into(),
            text: None,
            kind: None,
            source_application: None,
        });
    }
    #[cfg(target_os = "macos")]
    let source_application = match copy_macos_selection() {
        Ok(source) => source,
        Err(()) => {
            return Ok(SelectionCapture {
                status: "permission_required".into(),
                text: None,
                kind: None,
                source_application: None,
            })
        }
    };
    #[cfg(not(target_os = "macos"))]
    let source_application = None;

    // Windows and Linux require the user to copy the selection first. This is
    // intentional: it avoids accessibility/automation APIs that are absent or
    // blocked by a compositor, and makes the fallback explicit in the UI.
    let text = match arboard::Clipboard::new().and_then(|mut clipboard| clipboard.get_text()) {
        Ok(text) => text,
        Err(_) => {
            return Ok(SelectionCapture {
                status: "clipboard_unavailable".into(),
                text: None,
                kind: None,
                source_application,
            })
        }
    };
    let kind = match clipboard::classify(&text) {
        Ok(kind) => kind,
        Err("empty") => {
            return Ok(SelectionCapture {
                status: "empty_selection".into(),
                text: None,
                kind: None,
                source_application,
            })
        }
        Err(status) => {
            return Ok(SelectionCapture {
                status: status.into(),
                text: None,
                kind: None,
                source_application,
            })
        }
    };
    Ok(SelectionCapture {
        status: "candidate".into(),
        text: Some(text),
        kind: Some(kind.into()),
        source_application,
    })
}

#[cfg(target_os = "macos")]
fn copy_macos_selection() -> Result<Option<String>, ()> {
    let copy = Command::new("osascript")
        .args([
            "-e",
            "tell application \"System Events\" to keystroke \"c\" using command down",
        ])
        .status()
        .map_err(|_| ())?;
    if !copy.success() {
        return Err(());
    }
    let source = Command::new("osascript").args(["-e", "tell application \"System Events\" to get name of first application process whose frontmost is true"]).output().ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|value| value.trim().to_owned()).filter(|value| !value.is_empty());
    Ok(source)
}

pub fn plugin() -> tauri::plugin::TauriPlugin<tauri::Wry> {
    tauri_plugin_global_shortcut::Builder::new()
        .with_handler(|app, _shortcut, event| {
            if event.state == ShortcutState::Pressed {
                let _ = app.emit("selection-capture-requested", ());
            }
        })
        .build()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn defaults_match_each_platform() {
        assert!(!default_shortcut().is_empty());
        assert!(shortcut(default_shortcut()).is_ok());
    }
    #[test]
    fn malformed_shortcuts_are_rejected() {
        assert!(shortcut("").is_err());
    }
}
