//! The shell's one file of settings: `server.json` in the app's configuration
//! directory, read again on every launch.

use std::fs;
use std::io::ErrorKind;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, Url};

use crate::appearance::Appearance;
use crate::blobby::BlobbySettings;
use crate::local_work::Grant;
use crate::pinned::PinnedAgent;

#[derive(Serialize, Deserialize, Default)]
pub struct Settings {
    #[serde(default)]
    pub server_url: Option<Url>,
    #[serde(default)]
    pub appearance: Appearance,
    #[serde(default)]
    pub blobby: BlobbySettings,
    #[serde(default)]
    pub shortcuts: Shortcuts,
    #[serde(default)]
    pub window: WindowPreferences,
    /// Where AgenticOS lives for this person, chosen in onboarding; `None` before it.
    #[serde(default)]
    pub deployment: Option<Deployment>,
    /// Whether the console's welcome - blobby, shortcuts, notifications - has been through.
    #[serde(default)]
    pub onboarded: bool,
    /// The agents in the tray's and the Dock's "New Chat With", in order.
    #[serde(default)]
    pub pinned_agents: Vec<PinnedAgent>,
    /// The folders the person allowed their agents to work in on this computer.
    #[serde(default)]
    pub local_grants: Vec<Grant>,
    #[serde(default)]
    pub local_services: Vec<crate::local_services::Service>,
}

/// A stack the app set up on this machine, or an organization's server.
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Deployment {
    Local,
    Server,
}

/// What a global shortcut does.
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Hash, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    ScreenshotChat,
    QuickAsk,
    /// Push to talk: held, quick ask records; let go, the words are its question.
    Dictate,
    /// A voice call with the agent the chat has selected.
    VoiceCall,
}

impl Action {
    pub const ALL: [Action; 4] = [
        Action::ScreenshotChat,
        Action::QuickAsk,
        Action::Dictate,
        Action::VoiceCall,
    ];

    /// What a fresh install binds. A call costs minutes and starts talking at
    /// once, so it waits until somebody picks a combination for it.
    pub fn default_accelerator(self) -> Option<&'static str> {
        match self {
            Action::ScreenshotChat => Some("CmdOrCtrl+Shift+A"),
            Action::QuickAsk => Some("Alt+Space"),
            Action::Dictate => Some("Alt+Shift+Space"),
            Action::VoiceCall => None,
        }
    }
}

/// Global shortcuts, as accelerators the shortcut plugin parses (`CmdOrCtrl+Shift+A`).
/// `None` is a shortcut somebody switched off.
#[derive(Serialize, Deserialize, Clone, PartialEq, Debug)]
pub struct Shortcuts {
    #[serde(default = "default_screenshot")]
    pub screenshot_chat: Option<String>,
    #[serde(default = "default_quick_ask")]
    pub quick_ask: Option<String>,
    #[serde(default = "default_dictate")]
    pub dictate: Option<String>,
    #[serde(default)]
    pub voice_call: Option<String>,
}

fn default_for(action: Action) -> Option<String> {
    action.default_accelerator().map(str::to_owned)
}

fn default_screenshot() -> Option<String> {
    default_for(Action::ScreenshotChat)
}

fn default_quick_ask() -> Option<String> {
    default_for(Action::QuickAsk)
}

fn default_dictate() -> Option<String> {
    default_for(Action::Dictate)
}

impl Default for Shortcuts {
    fn default() -> Self {
        Self {
            screenshot_chat: default_screenshot(),
            quick_ask: default_quick_ask(),
            dictate: default_dictate(),
            voice_call: None,
        }
    }
}

impl Shortcuts {
    pub fn get(&self, action: Action) -> Option<&String> {
        match action {
            Action::ScreenshotChat => self.screenshot_chat.as_ref(),
            Action::QuickAsk => self.quick_ask.as_ref(),
            Action::Dictate => self.dictate.as_ref(),
            Action::VoiceCall => self.voice_call.as_ref(),
        }
    }

    pub fn set(&mut self, action: Action, accelerator: Option<String>) {
        match action {
            Action::ScreenshotChat => self.screenshot_chat = accelerator,
            Action::QuickAsk => self.quick_ask = accelerator,
            Action::Dictate => self.dictate = accelerator,
            Action::VoiceCall => self.voice_call = accelerator,
        }
    }
}

/// How the console's window behaves, beyond what it shows.
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
pub struct WindowPreferences {
    /// Closing the window hides it and the app keeps running in the menu bar or
    /// tray, the way a mail client does - and the way notifications, blobby and
    /// quick ask keep working with no window on screen.
    #[serde(default = "on_by_default")]
    pub keep_running: bool,
    /// The count of what is waiting for you, on the Dock icon and the tray.
    #[serde(default = "on_by_default")]
    pub badge: bool,
}

fn on_by_default() -> bool {
    true
}

impl Default for WindowPreferences {
    fn default() -> Self {
        Self {
            keep_running: true,
            badge: true,
        }
    }
}

fn path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("No configuration directory for this account: {e}"))?;
    Ok(dir.join("server.json"))
}

pub fn load(app: &AppHandle) -> Result<Settings, String> {
    let path = path(app)?;
    let raw = match fs::read_to_string(&path) {
        Ok(raw) => raw,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(Settings::default()),
        Err(e) => return Err(format!("Cannot read {}: {e}", path.display())),
    };
    serde_json::from_str(&raw).map_err(|e| format!("{} is not a saved shell configuration: {e}", path.display()))
}

/// The stored settings, or the defaults when the file cannot be read as settings.
///
/// A file that does not parse - a typo while hand-editing it, a partial write - is
/// set aside as `server.json.invalid` so that the connect form can save over it,
/// rather than fail on every submission with the very problem it is showing. The
/// second value says so, for the form.
pub fn load_or_quarantine(app: &AppHandle) -> (Settings, Option<String>) {
    let problem = match load(app) {
        Ok(settings) => return (settings, None),
        Err(problem) => problem,
    };
    eprintln!("{problem}");
    let notice = match path(app) {
        Ok(path) => {
            let aside = path.with_extension("json.invalid");
            match fs::rename(&path, &aside) {
                Ok(()) => format!("{problem} It was set aside as {}.", aside.display()),
                Err(e) => format!("{problem} It could not be set aside: {e}"),
            }
        }
        Err(e) => format!("{problem} {e}"),
    };
    (Settings::default(), Some(notice))
}

pub fn current(app: &AppHandle) -> Settings {
    load_or_quarantine(app).0
}

pub fn save(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    let path = path(app)?;
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("Cannot create {}: {e}", dir.display()))?;
    }
    let raw = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    fs::write(&path, raw).map_err(|e| format!("Cannot write {}: {e}", path.display()))
}

/// Read, change and write the settings in one step.
pub fn update<T>(app: &AppHandle, change: impl FnOnce(&mut Settings) -> T) -> Result<(Settings, T), String> {
    let mut settings = current(app);
    let outcome = change(&mut settings);
    save(app, &settings)?;
    Ok((settings, outcome))
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use tauri_plugin_global_shortcut::Shortcut;

    use super::{Action, Settings, Shortcuts, WindowPreferences};

    #[test]
    fn a_configuration_saved_before_shortcuts_existed_gets_the_default_bindings() {
        let settings: Settings = serde_json::from_str(r#"{"server_url":"https://agenticos.acme.com/"}"#).unwrap();
        for action in Action::ALL {
            assert_eq!(
                settings.shortcuts.get(action).map(String::as_str),
                action.default_accelerator()
            );
        }
    }

    #[test]
    fn a_shortcut_switched_off_stays_off() {
        let mut shortcuts = Shortcuts::default();
        shortcuts.set(Action::QuickAsk, None);
        let back: Shortcuts = serde_json::from_str(&serde_json::to_string(&shortcuts).unwrap()).unwrap();
        assert!(back.get(Action::QuickAsk).is_none());
        assert!(back.get(Action::ScreenshotChat).is_some());
    }

    #[test]
    fn every_default_binding_parses_as_a_shortcut() {
        for accelerator in Action::ALL.into_iter().filter_map(Action::default_accelerator) {
            assert!(Shortcut::from_str(accelerator).is_ok(), "{accelerator}");
        }
    }

    #[test]
    fn a_configuration_from_the_pet_era_still_loads() {
        // `pet` is no longer a field; a file written by an older shell keeps
        // its server and its shortcut, and blobby starts from its defaults.
        let settings: Settings = serde_json::from_str(
            r#"{"server_url":"https://agenticos.acme.com/","pet":{"enabled":false,"kind":"ghost"},"shortcuts":{"screenshot_chat":null}}"#,
        )
        .unwrap();
        assert_eq!(settings.server_url.unwrap().as_str(), "https://agenticos.acme.com/");
        assert!(settings.shortcuts.screenshot_chat.is_none());
        assert!(settings.blobby.enabled);
        assert_eq!(settings.window, WindowPreferences::default());
        assert_eq!(settings.deployment, None);
        assert!(!settings.onboarded);
    }
}
