//! An agent pinned to the phone (#2097), opening a new chat with it. The
//! console draws the face and names the agent. Android's half,
//! `PinShortcutPlugin.kt`, puts a launcher shortcut with that face on the home
//! screen; iOS lets no app do that, so `PinShortcutPlugin.swift` keeps the
//! agent for the Pinned agents widget, the app icon's menu and Shortcuts.

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(mobile)]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

const MAX_NAME_CHARS: usize = 80;
/// A launcher icon is a few hundred pixels; a megabyte is not an icon.
const MAX_ICON_BYTES: usize = 1024 * 1024;

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub struct Shortcut {
    pub id: String,
    pub name: String,
    /// A PNG, base64.
    pub icon: String,
}

/// The shortcut, or why it cannot be made: the id goes into a console path and
/// the name onto the home screen.
fn validate(shortcut: Shortcut) -> Result<Shortcut, String> {
    let is_uuid = shortcut.id.len() == 36
        && shortcut.id.chars().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => c == '-',
            _ => c.is_ascii_hexdigit(),
        });
    if !is_uuid {
        return Err("An agent's id is a UUID.".to_owned());
    }
    let name = shortcut.name.trim();
    if name.is_empty() || name.chars().any(char::is_control) {
        return Err("An agent's name is needed, on one line.".to_owned());
    }
    if shortcut.icon.is_empty() || shortcut.icon.len() > MAX_ICON_BYTES {
        return Err("The agent's face is missing or too large.".to_owned());
    }
    Ok(Shortcut {
        name: name.chars().take(MAX_NAME_CHARS).collect(),
        ..shortcut
    })
}

/// What happened: `pinned` is false where the launcher cannot pin, and the
/// agent is then only in the app icon's long-press list.
#[derive(Serialize, Deserialize, Debug, PartialEq, Eq)]
pub struct Pinned {
    pub pinned: bool,
}

#[cfg(mobile)]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_pin_shortcut);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("pin-shortcut")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(api.register_android_plugin(
                "co.vstorm.agenticos",
                "PinShortcutPlugin",
            )?));
            #[cfg(target_os = "ios")]
            app.manage(Native(api.register_ios_plugin(init_plugin_pin_shortcut)?));
            #[cfg(not(mobile))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

#[tauri::command]
pub fn pin_shortcut<R: Runtime>(app: AppHandle<R>, shortcut: Shortcut) -> Result<Pinned, String> {
    let shortcut = validate(shortcut)?;
    #[cfg(mobile)]
    {
        let native = app
            .try_state::<Native<R>>()
            .ok_or("Pinning is not set up.")?;
        native
            .0
            .run_mobile_plugin("pin", shortcut)
            .map_err(|e| e.to_string())
    }
    #[cfg(not(mobile))]
    {
        let _ = (app, shortcut);
        Err("Pinning to the home screen needs the Android app for now.".to_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::{validate, Shortcut};

    fn shortcut(id: &str, name: &str, icon: &str) -> Shortcut {
        Shortcut {
            id: id.into(),
            name: name.into(),
            icon: icon.into(),
        }
    }

    const ID: &str = "00000000-0000-4000-8000-000000000001";

    #[test]
    fn a_shortcut_names_an_agent_by_uuid_on_one_line_with_a_face() {
        assert_eq!(
            validate(shortcut(ID, " Support ", "iVBOR")).unwrap().name,
            "Support"
        );
        assert!(validate(shortcut("../settings", "x", "iVBOR")).is_err());
        assert!(validate(shortcut(
            "00000000x0000-4000-8000-000000000001",
            "x",
            "iVBOR"
        ))
        .is_err());
        assert!(validate(shortcut(ID, "two\nlines", "iVBOR")).is_err());
        assert!(validate(shortcut(ID, "Support", "")).is_err());
        assert!(validate(shortcut(ID, "Support", &"A".repeat(2 * 1024 * 1024))).is_err());
        assert_eq!(
            validate(shortcut(ID, &"n".repeat(200), "iVBOR"))
                .unwrap()
                .name
                .chars()
                .count(),
            80
        );
    }
}
