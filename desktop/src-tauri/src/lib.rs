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

mod credential;

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

    resolve(from_env.as_deref(), from_file.as_deref())
        .map(ApiConfig::from)
        .map_err(|err| err.to_string())
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_api_config,
            credential::credential_get,
            credential::credential_set,
            credential::credential_clear,
        ])
        .run(tauri::generate_context!())
        .expect("failed to start the LensWord desktop shell");
}
