//! Native credential storage for the desktop shell.
//!
//! ADR 0001 requires the authentication token to live in the operating-system
//! credential store rather than in webview `localStorage`, behind a typed
//! adapter exposing only get, set and clear. These three commands are that
//! adapter's host side; the frontend reaches them through
//! `apps/frontend/src/lib/credentialStore.ts`.
//!
//! The commands are thin delegations to the `keyring` crate — macOS Keychain,
//! Windows Credential Manager, and the Linux Secret Service. There is no branch
//! logic worth unit-testing here, and exercising it would touch the real OS
//! store; the behavioural gate ADR 0001 names is a packaged-app check on each
//! platform, not a unit test.

use keyring::{Entry, Error};

/// Service and account under which the single auth token is stored. Fixed
/// rather than derived from anything the webview supplies.
const SERVICE: &str = "com.lensword.desktop";
const ACCOUNT: &str = "auth-token";

fn entry() -> Result<Entry, String> {
    Entry::new(SERVICE, ACCOUNT).map_err(|err| err.to_string())
}

/// The stored token, or `None` when nothing has been stored yet.
///
/// Logging here never includes the token itself — only presence/absence and
/// failures — since log output can end up in a file on disk.
#[tauri::command]
pub fn credential_get() -> Result<Option<String>, String> {
    match entry()?.get_password() {
        Ok(token) => {
            log::debug!("credential_get: entry present");
            Ok(Some(token))
        }
        Err(Error::NoEntry) => {
            log::debug!("credential_get: no entry stored");
            Ok(None)
        }
        Err(err) => {
            log::error!("credential_get failed: {err}");
            Err(err.to_string())
        }
    }
}

/// Store or replace the token.
#[tauri::command]
pub fn credential_set(token: String) -> Result<(), String> {
    entry()?.set_password(&token).map_err(|err| {
        log::error!("credential_set failed: {err}");
        err.to_string()
    })
}

/// Remove the token. Clearing an already-absent credential is success, so a
/// logout after the store was cleared by other means does not error.
#[tauri::command]
pub fn credential_clear() -> Result<(), String> {
    match entry()?.delete_credential() {
        Ok(()) | Err(Error::NoEntry) => Ok(()),
        Err(err) => {
            log::error!("credential_clear failed: {err}");
            Err(err.to_string())
        }
    }
}
