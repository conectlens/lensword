//! LensWord desktop shell.
//!
//! The shell wraps the existing `frontend/` production build unchanged. Its
//! only responsibility beyond hosting that build is telling the frontend which
//! API endpoint it is permitted to talk to — resolved and validated here in the
//! host process, never in the webview.

use lensword_api_config::{resolve, Resolved};
use serde::Serialize;
use tauri::Manager;

/// Environment variable checked first, mainly so a developer can point the
/// shell at a scratch server without editing a file.
const API_BASE_ENV: &str = "LENSWORD_API_URL";

/// Plain-text file in the OS application-config directory holding one URL.
const CONFIG_FILE_NAME: &str = "api-endpoint";

/// What the frontend receives. `source` is included so the shell can show which
/// configuration layer won rather than leaving a surprising endpoint unexplained.
#[derive(Serialize)]
pub struct ApiConfig {
    pub base_url: String,
    pub source: String,
}

fn read_config_file(app: &tauri::AppHandle) -> Option<String> {
    let dir = app.path().app_config_dir().ok()?;
    std::fs::read_to_string(dir.join(CONFIG_FILE_NAME)).ok()
}

/// The single command this shell exposes.
///
/// Returning `Err` rather than falling back to the default is deliberate: a
/// misconfigured endpoint should surface as a visible failure, not as an app
/// that quietly talks to localhost while the user believes otherwise.
#[tauri::command]
fn get_api_config(app: tauri::AppHandle) -> Result<ApiConfig, String> {
    let from_env = std::env::var(API_BASE_ENV).ok();
    let from_file = read_config_file(&app);

    resolve(from_env.as_deref(), from_file.as_deref())
        .map(|Resolved { base_url, source }| ApiConfig {
            base_url,
            source: source.as_str().to_string(),
        })
        .map_err(|err| err.to_string())
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_api_config])
        .run(tauri::generate_context!())
        .expect("failed to start the LensWord desktop shell");
}
