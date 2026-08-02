//! LensWord desktop shell.
//!
//! The shell wraps the existing `frontend/` production build unchanged. Its
//! only responsibility beyond hosting that build is telling the frontend which
//! API endpoint it is permitted to talk to — resolved and validated in
//! `lensword-api-config`, in this process, never in the webview.
//!
//! The logic worth testing lives in that crate rather than here, so it can be
//! exercised without a webview toolchain. What remains in this file is the
//! Tauri wiring.

mod clipboard;
mod credential;
mod mcp;
mod selection_capture;

use lensword_api_config::{read_endpoint_file, resolve, ApiConfig};
use tauri::Manager;

/// Environment variable checked first, mainly so a developer can point the
/// shell at a scratch server without editing a file.
const API_BASE_ENV: &str = "LENSWORD_API_URL";

/// Plain-text file in the OS application-config directory holding one URL.
const CONFIG_FILE_NAME: &str = "api-endpoint";

fn config_file_contents(app: &tauri::AppHandle) -> Result<Option<String>, String> {
    let Ok(dir) = app.path().app_config_dir() else {
        // No resolvable config directory: nothing is configured, which is a
        // legitimate state rather than a failure.
        return Ok(None);
    };

    read_endpoint_file(&dir.join(CONFIG_FILE_NAME)).map_err(|err| {
        // Deliberately the file name and not the full path: the path contains
        // the user's home directory, and this string is rendered in the webview.
        format!("could not read the `{CONFIG_FILE_NAME}` configuration file: {err}")
    })
}

/// The single command this shell exposes.
///
/// Every failure is returned rather than swallowed. A file that exists but
/// cannot be read, or an endpoint that fails validation, must surface — falling
/// back to the loopback default would leave the app talking to localhost while
/// the user believes it is talking to the server they configured.
#[tauri::command]
fn get_api_config(app: tauri::AppHandle) -> Result<ApiConfig, String> {
    let from_env = std::env::var(API_BASE_ENV).ok();
    let from_file = config_file_contents(&app)?;

    let result = resolve(from_env.as_deref(), from_file.as_deref()).map(ApiConfig::from);
    match &result {
        Ok(config) => log::info!(
            "resolved API endpoint {} (source: {})",
            config.base_url,
            config.source
        ),
        Err(err) => log::error!("failed to resolve API endpoint: {err}"),
    }
    result.map_err(|err| err.to_string())
}

/// Set `RUST_LOG=lensword_desktop_lib=debug` (or `=trace`) to see per-command
/// tracing; unset, only warnings and errors print. Reads the env var itself
/// rather than deferring to env_logger's default (off), so a debug build with
/// no configuration still shows info-level output on stdout.
fn init_logging() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
}

pub fn run() {
    init_logging();

    tauri::Builder::default()
        // ROADMAP 3.2. The plugin's JS API is reached through a typed frontend
        // adapter (desktopNotifications.ts), not called from UI code directly.
        .plugin(tauri_plugin_notification::init())
        .plugin(selection_capture::plugin())
        .manage(mcp::McpState::default())
        .manage(clipboard::ClipboardState::default())
        .manage(selection_capture::SelectionCaptureState::default())
        .setup(|app| selection_capture::install(app.handle()).map_err(Into::into))
        .invoke_handler(tauri::generate_handler![
            get_api_config,
            credential::credential_get,
            credential::credential_set,
            credential::credential_clear,
            clipboard::clipboard_configure,
            clipboard::clipboard_status,
            clipboard::clipboard_capture,
            selection_capture::selection_capture_status,
            selection_capture::selection_capture_configure,
            selection_capture::selection_capture,
            mcp::mcp_server_list,
            mcp::mcp_server_save,
            mcp::mcp_server_delete,
            mcp::mcp_server_connect,
            mcp::mcp_server_disconnect,
            mcp::mcp_server_invoke,
        ])
        .run(tauri::generate_context!())
        .expect("failed to start the LensWord desktop shell");
}
