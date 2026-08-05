//! Launch-at-login, opt-in and reversible from Settings (issue #82).
//!
//! `tauri-plugin-autostart` already does the per-OS work — a launch agent on
//! macOS, a registry run key on Windows, a `.desktop` file on Linux — behind
//! one `AutoLaunchManager`. What this module adds is two narrow commands
//! wrapping it, rather than handing the frontend the plugin's own JS bindings
//! (ADR 0001): the frontend only ever needs "is it on" and "turn it on/off",
//! never the plugin's full surface.
use tauri::AppHandle;
use tauri_plugin_autostart::ManagerExt;

#[tauri::command]
pub fn autostart_status(app: AppHandle) -> Result<bool, String> {
    app.autolaunch().is_enabled().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn autostart_set_enabled(app: AppHandle, enabled: bool) -> Result<(), String> {
    let manager = app.autolaunch();
    let result = if enabled { manager.enable() } else { manager.disable() };
    result.map_err(|e| e.to_string())
}
