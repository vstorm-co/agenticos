//! What the console's pages may ask of the shell, and from where.
//!
//! The console is a remote page. Tauri refuses every command to a remote origin
//! unless a capability names it, so the shell grants one at runtime for the one
//! origin the person configured - and for each of its windows only the commands
//! that window's page uses. A page anywhere else, including one the console
//! window was sent to during an OAuth consent, reaches none of them.
//!
//! What is granted is deliberately small: settings the person could change from
//! the menu anyway, a notification, a badge, a window to open. Nothing here runs
//! arbitrary commands or holds a credential. File reads are bounded to folders
//! the person granted through the native picker; adding a local service asks
//! again in a native dialog. Injected scripts inherit these page permissions.

use std::collections::HashSet;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::ipc::CapabilityBuilder;
use tauri::{AppHandle, Manager, Url, WebviewWindow};
use tauri_plugin_autostart::ManagerExt;

use crate::appearance::{self, Appearance, Surface};
use crate::blobby::{self, BlobbySettings};
use crate::notify::{self, Notice};
use crate::pinned::{self, PinnedAgent};
use crate::settings::{self, WindowPreferences};
use crate::shortcuts::{self, Binding};
use crate::{quick_ask, WINDOW};

/// The commands and core permissions a window's page is granted, per window.
///
/// Kept beside each other so the review of what a remote page may do is one
/// table, and so the test below can hold it to the commands the shell defines.
pub const GRANTS: &[(&str, &[&str])] = &[
    (
        WINDOW,
        &[
            "allow-native-browser-view",
            "allow-desktop-state",
            "allow-desktop-activity",
            "allow-desktop-retry-screenshot",
            "allow-desktop-readiness",
            "allow-desktop-request-permission",
            "allow-desktop-is-focused",
            "allow-change-server",
            "allow-set-appearance",
            "allow-set-blobby",
            "allow-set-shortcut",
            "allow-set-window-preferences",
            "allow-notify",
            "allow-set-badge",
            "allow-finish-onboarding",
            "allow-take-shared",
            "allow-pin-agent",
            "allow-unpin-agent",
            "allow-device-status",
            "allow-device-link",
            "allow-device-unlink",
            "allow-local-allow-computer",
            "allow-local-revoke-computer",
            "allow-local-grants",
            "allow-local-pick-folder",
            "allow-local-revoke",
            "allow-local-files",
            "allow-local-file",
            "allow-local-services",
            "allow-local-save-service",
            "allow-local-remove-service",
            "allow-page-error",
            "core:event:allow-listen",
            "core:event:allow-unlisten",
            "core:window:allow-start-dragging",
            "core:window:allow-internal-toggle-maximize",
        ],
    ),
    (
        blobby::WINDOW,
        &[
            "allow-desktop-state",
            "allow-save-blobby-position",
            "allow-resize-blobby",
            "allow-blobby-menu",
            "allow-open-in-console",
            "allow-open-chat",
            "allow-show-console",
            "allow-page-error",
            "core:event:allow-listen",
            "core:event:allow-unlisten",
            "core:window:allow-start-dragging",
            "core:window:allow-set-position",
            "core:window:allow-outer-position",
            "core:window:allow-outer-size",
            "core:window:allow-scale-factor",
            "core:window:allow-current-monitor",
            "core:window:allow-cursor-position",
        ],
    ),
    (
        quick_ask::WINDOW,
        &[
            "allow-desktop-state",
            "allow-desktop-activity",
            "allow-resize-quick-ask",
            "allow-hide-quick-ask",
            "allow-quick-ask-pinned",
            "allow-set-quick-ask-pinned",
            "allow-set-quick-ask-picker-open",
            "allow-take-context-files",
            "allow-open-accessibility-settings",
            "allow-open-in-console",
            "allow-page-error",
            "core:event:allow-listen",
            "core:event:allow-unlisten",
            "core:window:allow-start-dragging",
        ],
    ),
];

/// Origins already granted. A capability cannot be taken back at runtime, so a
/// server changed mid-session keeps its grant until the shell restarts - which
/// matters only if the old server is loaded again, and it is the person's own.
#[derive(Default)]
pub struct Granted(Mutex<HashSet<String>>);

/// The pattern a remote capability matches: every page on the server's origin.
pub fn origin_pattern(server: &Url) -> String {
    format!("{}/*", server.origin().ascii_serialization())
}

/// Grant the console's windows their commands, on the server's origin only.
pub fn grant(app: &AppHandle, server: &Url) -> Result<(), String> {
    let pattern = origin_pattern(server);
    let granted = app.state::<Granted>();
    let mut seen = granted.0.lock().map_err(|e| e.to_string())?;
    if !seen.insert(pattern.clone()) {
        return Ok(());
    }
    for (window, permissions) in GRANTS {
        let capability = capability_for(window, permissions, &pattern);
        app.add_capability(capability).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn capability_for(webview: &str, permissions: &[&str], pattern: &str) -> CapabilityBuilder {
    permissions.iter().fold(
        CapabilityBuilder::new(format!("console-{webview}-{pattern}"))
            .remote(pattern.to_owned())
            .local(false)
            .webview(webview),
        |capability, permission| capability.permission(*permission),
    )
}

/// Everything the desktop tabs in the console's settings show.
#[derive(Serialize)]
pub struct DesktopState {
    pub connection_revision: String,
    pub appearance: Appearance,
    pub blobby: BlobbySettings,
    /// The agents in "New Chat With", in order.
    pub pinned: Vec<PinnedAgent>,
    pub shortcuts: Vec<Binding>,
    pub window: WindowView,
}

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
pub struct WindowView {
    pub keep_running: bool,
    pub badge: bool,
    /// The operating system's to keep - a login item on macOS, a registry key on
    /// Windows, an autostart entry on Linux - and read from it, never from the file.
    pub launch_at_login: bool,
}

#[tauri::command]
pub fn desktop_state(app: AppHandle) -> DesktopState {
    let settings = settings::current(&app);
    let launch_at_login = app.autolaunch().is_enabled().unwrap_or(false);
    DesktopState {
        connection_revision: settings.connection_revision,
        appearance: settings.appearance,
        shortcuts: shortcuts::views(&app, &settings.shortcuts),
        blobby: settings.blobby,
        pinned: settings.pinned_agents,
        window: WindowView {
            keep_running: settings.window.keep_running,
            badge: settings.window.badge,
            launch_at_login,
        },
    }
}

/// The console's style changed: remember it for the next launch and dress every window in it.
#[tauri::command]
pub fn set_appearance(app: AppHandle, appearance: Appearance) -> Result<(), String> {
    if settings::current(&app).appearance != appearance {
        settings::update(&app, |settings| settings.appearance = appearance)?;
    }
    for (label, surface) in [(WINDOW, Surface::Console), (quick_ask::WINDOW, Surface::Panel)] {
        if let Some(window) = app.get_webview_window(label) {
            if label == WINDOW {
                let surface = crate::page_surface(&window.url().map_err(|e| e.to_string())?);
                crate::dress(&window, surface, appearance).map_err(|e| e.to_string())?;
            } else {
                appearance::apply(&window, surface, appearance).map_err(|e| e.to_string())?;
            }
        }
    }
    let settings = settings::current(&app);
    blobby::sync(&app, settings.server_url.as_ref(), &settings.blobby)
}

/// Blobby's settings from the desktop tab. Where it was left is the shell's, not the page's.
#[tauri::command]
pub fn set_blobby(app: AppHandle, blobby: BlobbySettings) -> Result<(), String> {
    blobby::validate(&blobby.character)?;
    let blobby = BlobbySettings {
        size: blobby::clamp_scale(blobby.size),
        ..blobby
    };
    let (settings, ()) = settings::update(&app, |settings| {
        settings.blobby = BlobbySettings {
            position: settings.blobby.position,
            ..blobby
        };
    })?;
    crate::reflect_blobby(&app, &settings)
}

/// Blobby made bigger or smaller on the desktop - a pinch, or the scroll wheel with ⌘.
#[tauri::command]
pub fn resize_blobby(app: AppHandle, size: f64) -> Result<(), String> {
    let size = blobby::clamp_scale(size);
    let (settings, ()) = settings::update(&app, |settings| settings.blobby.size = size)?;
    crate::reflect_blobby(&app, &settings)
}

#[tauri::command]
pub fn save_blobby_position(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    if !x.is_finite() || !y.is_finite() {
        return Err("A position is two finite numbers.".to_owned());
    }
    settings::update(&app, |settings| {
        settings.blobby.position = Some(blobby::Position { x, y });
    })
    .map(|_| ())
}

#[tauri::command]
pub fn set_window_preferences(app: AppHandle, preferences: WindowView) -> Result<(), String> {
    let autolaunch = app.autolaunch();
    let result = if preferences.launch_at_login {
        autolaunch.enable()
    } else {
        autolaunch.disable()
    };
    result.map_err(|e| format!("Cannot change whether AgenticOS opens at login: {e}"))?;
    settings::update(&app, |settings| {
        settings.window = WindowPreferences {
            keep_running: preferences.keep_running,
            badge: preferences.badge,
        };
    })?;
    if !preferences.badge {
        set_badge(app, 0)?;
    }
    Ok(())
}

#[tauri::command]
pub fn notify(app: AppHandle, notice: Notice) -> Result<(), String> {
    notify::show(&app, notice)
}

/// What is waiting for this person, on the Dock icon and beside the tray icon.
#[tauri::command]
pub fn set_badge(app: AppHandle, count: u32) -> Result<(), String> {
    let shown = settings::current(&app).window.badge && count > 0;
    if let Some(console) = app.get_webview_window(WINDOW) {
        console
            .set_badge_count(shown.then_some(i64::from(count)))
            .map_err(|e| e.to_string())?;
    }
    crate::tray_badge(&app, shown.then_some(count))
}

/// Bring the console forward on one of its own pages - from blobby's bubble, from
/// quick ask's "open in console", from a notification.
#[tauri::command]
pub fn open_in_console(app: AppHandle, path: String) -> Result<(), String> {
    crate::open_in_console_at(&app, &path)
}

/// Pin an agent to the tray's and the Dock's "New Chat With", or rename one
/// already there. Answers the list as it now stands.
#[tauri::command]
pub fn pin_agent(app: AppHandle, agent: PinnedAgent) -> Result<Vec<PinnedAgent>, String> {
    let agent = pinned::validate(&agent)?;
    let current = settings::current(&app).pinned_agents;
    let next = pinned::pin(&current, agent)?;
    save_pinned(&app, next)
}

#[tauri::command]
pub fn unpin_agent(app: AppHandle, id: String) -> Result<Vec<PinnedAgent>, String> {
    let next = pinned::unpin(&settings::current(&app).pinned_agents, &id);
    save_pinned(&app, next)
}

fn save_pinned(app: &AppHandle, pinned: Vec<PinnedAgent>) -> Result<Vec<PinnedAgent>, String> {
    settings::update(app, |settings| settings.pinned_agents = pinned.clone())?;
    crate::reflect_pinned(app, &pinned)?;
    Ok(pinned)
}

/// Blobby's own menu, under the right mouse button.
#[tauri::command]
pub fn blobby_menu(app: AppHandle, window: WebviewWindow) -> Result<(), String> {
    crate::popup_tray_menu(&app, &window)
}

#[cfg(test)]
mod tests {
    use tauri::Url;

    use super::{origin_pattern, GRANTS, WINDOW};

    #[test]
    fn installers_and_instance_creation_belong_only_to_local_setup() {
        let setup: serde_json::Value = serde_json::from_str(include_str!("../capabilities/default.json")).unwrap();
        let permissions = setup["permissions"].as_array().unwrap();
        for permission in [
            "allow-download-docker",
            "allow-open-docker",
            "allow-local-instances",
            "allow-set-up-local",
        ] {
            assert!(permissions.iter().any(|value| value.as_str() == Some(permission)));
            assert!(GRANTS.iter().all(|(_, grants)| !grants.contains(&permission)));
        }
    }

    #[test]
    fn a_grant_covers_the_servers_origin_and_nothing_wider() {
        let server = Url::parse("https://agenticos.acme.com/pl/chat?id=1").unwrap();
        assert_eq!(origin_pattern(&server), "https://agenticos.acme.com/*");
        let local = Url::parse("http://localhost:3000/").unwrap();
        assert_eq!(origin_pattern(&local), "http://localhost:3000/*");
    }

    #[test]
    fn every_granted_command_is_one_the_shell_registers() {
        // A typo here is a page that silently cannot call its command; a
        // command granted that the shell no longer has is a grant to review.
        let manifest = include_str!("../build.rs");
        for (window, permissions) in GRANTS {
            for permission in permissions.iter().filter(|p| p.starts_with("allow-")) {
                let command = permission.trim_start_matches("allow-").replace('-', "_");
                assert!(
                    manifest.contains(&format!("\"{command}\"")),
                    "{window} is granted {permission}, which build.rs does not declare"
                );
            }
        }
    }

    #[test]
    fn only_quick_ask_may_change_its_focus_policy() {
        for (window, permissions) in GRANTS {
            for permission in [
                "allow-quick-ask-pinned",
                "allow-set-quick-ask-pinned",
                "allow-set-quick-ask-picker-open",
            ] {
                assert_eq!(permissions.contains(&permission), *window == crate::quick_ask::WINDOW);
            }
        }
    }

    #[test]
    fn activity_is_granted_only_to_the_main_chat_and_quick_ask() {
        for (window, permissions) in GRANTS {
            assert_eq!(
                permissions.contains(&"allow-desktop-activity"),
                *window == WINDOW || *window == crate::quick_ask::WINDOW
            );
        }
    }

    #[test]
    fn no_remote_window_is_granted_a_way_to_run_or_read_anything() {
        for (window, permissions) in GRANTS {
            for permission in *permissions {
                if *permission == "allow-desktop-retry-screenshot" {
                    // This opens macOS's interactive region picker. It accepts no
                    // path or capture parameters and shares nothing until the person selects a region.
                    assert_eq!(*window, WINDOW);
                    continue;
                }
                for refused in ["shell", "fs:", "opener", "process", "http:", "connect", "screenshot"] {
                    assert!(!permission.contains(refused), "{window} is granted {permission}");
                }
            }
        }
    }

    #[test]
    fn only_the_main_console_may_open_the_server_picker() {
        for (window, permissions) in GRANTS {
            assert_eq!(permissions.contains(&"allow-change-server"), *window == WINDOW);
        }
    }
    #[test]
    fn console_capabilities_do_not_extend_to_child_pages_in_the_same_window() {
        use tauri::ipc::RuntimeCapability;
        use tauri::utils::acl::capability::CapabilityFile;
        let CapabilityFile::Capability(capability) =
            super::capability_for("main", &["allow-device-status"], "https://agents.example/*").build()
        else {
            panic!("Expected one capability");
        };
        assert!(capability.windows.is_empty());
        assert_eq!(capability.webviews, vec!["main"]);
        assert!(!capability
            .webviews
            .iter()
            .any(|view| view.starts_with("native-browser-")));
    }
}
