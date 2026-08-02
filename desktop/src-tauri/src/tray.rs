//! Tray / menu-bar presence and quick actions (issue #82).
//!
//! Two things this module owns, and the second is the one that goes wrong.
//!
//! **Staying available after the window closes.** On macOS an application
//! outliving its last window is the platform convention; on Windows and Linux
//! it is not, and a process that keeps running after the user pressed the
//! close button reads as a bug or worse. So close-to-tray is per-OS, and the
//! decision is `close_behaviour()` rather than scattered `#[cfg]` blocks.
//!
//! **Quitting for real.** Explicit Quit has to end the process tree, not just
//! hide a window — a shell that lingers invisible is the thing users
//! uninstall over. `Quit` therefore calls `app.exit`, which runs Tauri's
//! shutdown and drops the webview, rather than closing windows one by one.
//!
//! Where an action leads is *not* decided here. The shell emits
//! `tray://action` and the typed frontend adapter maps it to a route — the
//! shell does not own the router, and a second copy of the routing table in
//! Rust would drift from the real one.
//!
//! Actions are a closed enum with stable string ids. They travel to the OS
//! menu and come back as strings, so renaming a variant would silently break
//! a menu item rather than fail to compile — the same reasoning as the
//! notification action ids in the backend.
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuEvent, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, State,
};

/// What the tray can be asked to do.
///
/// Every variant either navigates the main window or toggles a setting.
/// Nothing here mutates vocabulary: a menu is the wrong place to be one
/// mis-click away from changing someone's data.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TrayAction {
    AddWord,
    QuickReview,
    TogglePause,
    ShowWindow,
    Quit,
}

impl TrayAction {
    /// Stable id used as the OS menu item identifier.
    pub const fn id(self) -> &'static str {
        match self {
            Self::AddWord => "tray_add_word",
            Self::QuickReview => "tray_quick_review",
            Self::TogglePause => "tray_toggle_pause",
            Self::ShowWindow => "tray_show_window",
            Self::Quit => "tray_quit",
        }
    }

    pub fn from_id(id: &str) -> Option<Self> {
        [
            Self::AddWord,
            Self::QuickReview,
            Self::TogglePause,
            Self::ShowWindow,
            Self::Quit,
        ]
        .into_iter()
        .find(|action| action.id() == id)
    }
}

/// What closing the main window should do on this platform.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CloseBehaviour {
    /// Hide the window, keep the process. The macOS convention.
    HideToTray,
    /// Actually exit. What Windows and Linux users expect from the close
    /// button, where a lingering background process is a surprise.
    Exit,
}

pub const fn close_behaviour() -> CloseBehaviour {
    if cfg!(target_os = "macos") {
        CloseBehaviour::HideToTray
    } else {
        CloseBehaviour::Exit
    }
}

/// Counts and states the tray label reflects.
///
/// Pushed from the frontend rather than read here. The shell has no session
/// and no database; asking it to compute a due count would mean a second
/// authenticated API client in a second language.
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TrayStatus {
    pub due_count: u32,
    pub notifications_paused: bool,
    /// Display name of the current AI provider, or None when disabled.
    pub ai_provider: Option<String>,
    /// Whether a local model is reachable. `None` means not yet checked —
    /// distinguished from `Some(false)` so the menu can say "checking" rather
    /// than asserting an outage it has not observed.
    pub local_model_ready: Option<bool>,
}

impl TrayStatus {
    /// The single line shown as the tray tooltip.
    pub fn summary(&self) -> String {
        let mut parts = vec![if self.due_count == 0 {
            "No words due".to_string()
        } else {
            format!("{} word(s) due", self.due_count)
        }];
        if self.notifications_paused {
            parts.push("reminders paused".into());
        }
        match (&self.ai_provider, self.local_model_ready) {
            (Some(name), Some(true)) => parts.push(format!("{name} ready")),
            (Some(name), Some(false)) => parts.push(format!("{name} unavailable")),
            (Some(name), None) => parts.push(format!("{name} checking")),
            (None, _) => {}
        }
        parts.join(" · ")
    }
}

#[derive(Default)]
pub struct TrayState(pub Mutex<TrayStatus>);

/// Push current counts into the tray. Called by the frontend.
#[tauri::command]
pub fn tray_set_status(
    app: AppHandle,
    state: State<'_, TrayState>,
    status: TrayStatus,
) -> Result<(), String> {
    let summary = status.summary();
    *state.0.lock().map_err(|_| "tray state is poisoned")? = status;
    if let Some(tray) = app.tray_by_id("main") {
        tray.set_tooltip(Some(&summary))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn tray_status(state: State<'_, TrayState>) -> Result<TrayStatus, String> {
    Ok(state
        .0
        .lock()
        .map_err(|_| "tray state is poisoned")?
        .clone())
}

/// Build the tray and wire its menu.
pub fn install(app: &AppHandle) -> tauri::Result<()> {
    let items = [
        (TrayAction::ShowWindow, "Open LensWord"),
        (TrayAction::AddWord, "Add word"),
        (TrayAction::QuickReview, "Five-minute review"),
        (TrayAction::TogglePause, "Pause reminders"),
        (TrayAction::Quit, "Quit"),
    ];
    let mut built = Vec::new();
    for (action, label) in items {
        built.push(MenuItem::with_id(
            app,
            action.id(),
            label,
            true,
            None::<&str>,
        )?);
    }
    let refs: Vec<&dyn tauri::menu::IsMenuItem<_>> = built
        .iter()
        .map(|i| i as &dyn tauri::menu::IsMenuItem<_>)
        .collect();
    let menu = Menu::with_items(app, &refs)?;

    TrayIconBuilder::with_id("main")
        .menu(&menu)
        .tooltip("LensWord")
        .icon(app.default_window_icon().cloned().ok_or_else(|| {
            tauri::Error::AssetNotFound("no default window icon for the tray".into())
        })?)
        .on_menu_event(handle_menu_event)
        .build(app)?;
    Ok(())
}

fn handle_menu_event(app: &AppHandle, event: MenuEvent) {
    let Some(action) = TrayAction::from_id(event.id().as_ref()) else {
        return;
    };
    if action == TrayAction::Quit {
        // Ends the process tree rather than closing windows one at a time. A
        // shell that lingers invisibly after Quit is what users uninstall over.
        app.exit(0);
        return;
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
    // The action is emitted rather than acted on here. UI code must not call
    // Tauri APIs directly (issue #82), and equally the shell must not own the
    // frontend's routing table — so it says what happened and the typed
    // frontend adapter decides where to go.
    let _ = app.emit("tray://action", action);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn action_ids_round_trip() {
        // Ids travel to the OS menu and come back as strings. A variant whose
        // id did not round-trip would produce a menu item that silently does
        // nothing rather than a compile error.
        for action in [
            TrayAction::AddWord,
            TrayAction::QuickReview,
            TrayAction::TogglePause,
            TrayAction::ShowWindow,
            TrayAction::Quit,
        ] {
            assert_eq!(TrayAction::from_id(action.id()), Some(action));
        }
    }

    #[test]
    fn unknown_ids_are_ignored_rather_than_panicking() {
        // The OS can deliver menu events this build does not know about, for
        // instance after an update replaces the menu.
        assert_eq!(TrayAction::from_id("tray_nonexistent"), None);
    }

    #[test]
    fn action_ids_are_unique() {
        let ids = [
            TrayAction::AddWord.id(),
            TrayAction::QuickReview.id(),
            TrayAction::TogglePause.id(),
            TrayAction::ShowWindow.id(),
            TrayAction::Quit.id(),
        ];
        let mut seen = ids.to_vec();
        seen.sort_unstable();
        seen.dedup();
        assert_eq!(seen.len(), ids.len(), "two actions share a menu id");
    }

    #[test]
    fn closing_hides_on_macos_and_exits_elsewhere() {
        // The platform convention differs, and getting it backwards is what
        // makes a shell feel broken: a lingering process on Windows, or an app
        // that quits when you close a window on macOS.
        let expected = if cfg!(target_os = "macos") {
            CloseBehaviour::HideToTray
        } else {
            CloseBehaviour::Exit
        };
        assert_eq!(close_behaviour(), expected);
    }

    #[test]
    fn the_summary_reads_naturally_with_nothing_due() {
        let status = TrayStatus::default();
        assert_eq!(status.summary(), "No words due");
    }

    #[test]
    fn the_summary_reports_counts_pause_and_provider() {
        let status = TrayStatus {
            due_count: 5,
            notifications_paused: true,
            ai_provider: Some("Ollama".into()),
            local_model_ready: Some(true),
        };
        assert_eq!(
            status.summary(),
            "5 word(s) due · reminders paused · Ollama ready"
        );
    }

    #[test]
    fn an_unchecked_model_says_checking_rather_than_unavailable() {
        // None and Some(false) are different claims. Collapsing them would
        // report an outage the shell has not observed.
        let status = TrayStatus {
            ai_provider: Some("Ollama".into()),
            local_model_ready: None,
            ..Default::default()
        };
        assert!(status.summary().ends_with("Ollama checking"));
    }

    #[test]
    fn a_disabled_provider_is_not_mentioned() {
        let status = TrayStatus {
            due_count: 1,
            ai_provider: None,
            ..Default::default()
        };
        assert_eq!(status.summary(), "1 word(s) due");
    }
}
