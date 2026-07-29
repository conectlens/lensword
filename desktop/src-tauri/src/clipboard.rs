//! Permission-aware clipboard capture. Raw clipboard strings never enter disk
//! storage or logs; the caller receives a transient candidate only after all
//! local policy checks pass.
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::State;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClipboardConfig {
    pub enabled: bool,
    pub paused: bool,
    pub blocked_apps: Vec<String>,
}
impl Default for ClipboardConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            paused: false,
            blocked_apps: vec![],
        }
    }
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClipboardCapture {
    pub status: String,
    pub text: Option<String>,
    pub kind: Option<String>,
}
#[derive(Default)]
pub struct ClipboardState {
    inner: Mutex<Inner>,
}
#[derive(Default)]
struct Inner {
    config: ClipboardConfig,
    recent: HashSet<u64>,
    last_capture: Option<Instant>,
}

fn classify(text: &str) -> Result<&'static str, &'static str> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Err("empty");
    }
    if trimmed.len() > 10_000 {
        return Err("too_large");
    }
    let lower = trimmed.to_ascii_lowercase();
    if lower.contains("password")
        || lower.contains("bearer ")
        || lower.contains("api_key")
        || lower.contains("secret")
        || looks_like_card(trimmed)
    {
        return Err("sensitive");
    }
    Ok(if trimmed.split_whitespace().count() == 1 {
        "word"
    } else {
        "paragraph"
    })
}
fn looks_like_card(text: &str) -> bool {
    let digits: String = text.chars().filter(char::is_ascii_digit).collect();
    (13..=19).contains(&digits.len())
        && digits.chars().enumerate().fold(0, |sum, (index, digit)| {
            let mut value = digit.to_digit(10).unwrap_or(0);
            if index % 2 == digits.len() % 2 {
                value *= 2;
                if value > 9 {
                    value -= 9;
                }
            }
            sum + value
        }) % 10
            == 0
}
fn fingerprint(text: &str) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    text.hash(&mut h);
    h.finish()
}

#[tauri::command]
pub fn clipboard_configure(
    config: ClipboardConfig,
    state: State<'_, ClipboardState>,
) -> Result<(), String> {
    state
        .inner
        .lock()
        .map_err(|_| "clipboard state unavailable")?
        .config = config;
    Ok(())
}
#[tauri::command]
pub fn clipboard_status(state: State<'_, ClipboardState>) -> Result<ClipboardConfig, String> {
    Ok(state
        .inner
        .lock()
        .map_err(|_| "clipboard state unavailable")?
        .config
        .clone())
}
#[tauri::command]
pub fn clipboard_capture(
    source_application: Option<String>,
    state: State<'_, ClipboardState>,
) -> Result<ClipboardCapture, String> {
    let mut state = state
        .inner
        .lock()
        .map_err(|_| "clipboard state unavailable")?;
    if !state.config.enabled {
        return Ok(ClipboardCapture {
            status: "disabled".into(),
            text: None,
            kind: None,
        });
    }
    if state.config.paused {
        return Ok(ClipboardCapture {
            status: "paused".into(),
            text: None,
            kind: None,
        });
    }
    if source_application.as_ref().is_some_and(|app| {
        state
            .config
            .blocked_apps
            .iter()
            .any(|blocked| blocked.eq_ignore_ascii_case(app))
    }) {
        return Ok(ClipboardCapture {
            status: "blocked_application".into(),
            text: None,
            kind: None,
        });
    }
    if state
        .last_capture
        .is_some_and(|at| at.elapsed() < Duration::from_secs(2))
    {
        return Ok(ClipboardCapture {
            status: "throttled".into(),
            text: None,
            kind: None,
        });
    }
    // Creating the native clipboard object happens only after opt-in checks.
    let text = arboard::Clipboard::new()
        .map_err(|_| "clipboard_unavailable")?
        .get_text()
        .map_err(|_| "clipboard_unavailable")?;
    let kind = match classify(&text) {
        Ok(kind) => kind,
        Err(status) => {
            return Ok(ClipboardCapture {
                status: status.into(),
                text: None,
                kind: None,
            })
        }
    };
    if !state.recent.insert(fingerprint(&text)) {
        return Ok(ClipboardCapture {
            status: "duplicate".into(),
            text: None,
            kind: None,
        });
    }
    state.last_capture = Some(Instant::now());
    Ok(ClipboardCapture {
        status: "candidate".into(),
        text: Some(text),
        kind: Some(kind.into()),
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sensitive_values_and_cards_are_never_candidates() {
        assert_eq!(classify("Bearer abc").unwrap_err(), "sensitive");
        assert_eq!(classify("4111 1111 1111 1111").unwrap_err(), "sensitive");
        assert_eq!(classify("hola").unwrap(), "word");
        assert_eq!(classify("hola mundo").unwrap(), "paragraph");
    }
}
