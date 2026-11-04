//! Global shortcuts: opening the console, the screenshot to a new chat, quick ask, push-to-talk
//! dictation into it, and a voice call.

use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

use crate::settings::{self, Action};

/// The accelerators actually registered with the system - which are not the ones
/// in the settings when another application held one at start-up.
#[derive(Default)]
pub struct Bindings(Mutex<HashMap<Action, String>>);

fn bound(app: &AppHandle, action: Action) -> Option<String> {
    app.state::<Bindings>()
        .0
        .lock()
        .ok()
        .and_then(|bindings| bindings.get(&action).cloned())
}

fn perform(app: &AppHandle, action: Action, state: ShortcutState) {
    let pressed = state == ShortcutState::Pressed;
    let result = match action {
        // Push to talk is the one shortcut whose release means something.
        Action::Dictate => {
            let settings = settings::current(app);
            crate::quick_ask::dictate(app, settings.server_url.as_ref(), settings.appearance, pressed)
        }
        _ if !pressed => Ok(()),
        Action::OpenConsole => crate::bring_console(app),
        Action::ScreenshotChat => {
            crate::screenshot_to_chat(app);
            Ok(())
        }
        Action::QuickAsk => {
            let settings = settings::current(app);
            crate::quick_ask::toggle(app, settings.server_url.as_ref(), settings.appearance)
        }
        Action::VoiceCall => crate::start_in_chat(app, "call"),
    };
    if let Err(e) = result {
        eprintln!("{action:?}: {e}");
    }
}

pub fn register(app: &AppHandle, action: Action, accelerator: &str) -> Result<(), String> {
    let shortcut = Shortcut::from_str(accelerator).map_err(|e| format!("{accelerator} is not a shortcut: {e}"))?;
    app.global_shortcut()
        .on_shortcut(shortcut, move |app, _shortcut, event| perform(app, action, event.state))
        .map_err(|e| format!("Cannot bind {accelerator}: {e}"))?;
    if let Ok(mut bindings) = app.state::<Bindings>().0.lock() {
        bindings.insert(action, accelerator.to_owned());
    }
    Ok(())
}

fn unregister(app: &AppHandle, action: Action, accelerator: &str) {
    if let Err(e) = app.global_shortcut().unregister(accelerator) {
        eprintln!("could not release {accelerator}: {e}");
    }
    if let Ok(mut bindings) = app.state::<Bindings>().0.lock() {
        bindings.remove(&action);
    }
}

/// Bind every shortcut the settings name, reporting each one that cannot be taken.
pub fn register_all(app: &AppHandle, shortcuts: &settings::Shortcuts) {
    for action in Action::ALL {
        if let Some(accelerator) = shortcuts.get(action) {
            if let Err(e) = register(app, action, accelerator) {
                eprintln!("{e}");
            }
        }
    }
    if let Err(e) = app.state::<crate::ShellMenu>().reflect_shortcuts(app) {
        eprintln!("shortcut menu: {e}");
    }
}

/// One shortcut as configured, and what is wrong with it if anything is.
#[derive(Serialize, Debug, PartialEq)]
pub struct Binding {
    pub action: Action,
    pub accelerator: Option<String>,
    pub problem: Option<String>,
}

impl Binding {
    /// A menu must not advertise a shortcut that could not be registered.
    pub fn menu_accelerator(&self) -> Option<&str> {
        if self.problem.is_some() {
            None
        } else {
            self.accelerator.as_deref()
        }
    }
}

pub fn view(configured: Option<&String>, held: Option<&String>, action: Action) -> Binding {
    let problem = match (configured, held) {
        (Some(wanted), Some(held)) if wanted == held => None,
        (Some(wanted), _) => Some(format!(
            "{wanted} could not be bound - another application holds it. Pick another combination."
        )),
        (None, _) => None,
    };
    Binding {
        action,
        accelerator: configured.cloned(),
        problem,
    }
}

pub fn views(app: &AppHandle, shortcuts: &settings::Shortcuts) -> Vec<Binding> {
    Action::ALL
        .into_iter()
        .map(|action| view(shortcuts.get(action), bound(app, action).as_ref(), action))
        .collect()
}

/// Rebind, or switch off, one shortcut. Answers with what is now bound.
///
/// The old binding is released first and put back if the new one cannot be taken,
/// so a combination another application holds leaves the shell where it was.
#[tauri::command]
pub fn set_shortcut(app: AppHandle, action: Action, accelerator: Option<String>) -> Result<Option<String>, String> {
    let wanted = accelerator.map(|a| a.trim().to_owned()).filter(|a| !a.is_empty());
    let current = settings::current(&app).shortcuts.get(action).cloned();
    if let Some(old) = &current {
        unregister(&app, action, old);
    }
    if let Some(new) = &wanted {
        if let Err(refusal) = register(&app, action, new) {
            if let Some(old) = &current {
                if let Err(e) = register(&app, action, old) {
                    eprintln!("could not put {old} back: {e}");
                }
            }
            if let Err(e) = app.state::<crate::ShellMenu>().reflect_shortcuts(&app) {
                eprintln!("shortcut menu: {e}");
            }
            return Err(refusal);
        }
    }
    settings::update(&app, |settings| settings.shortcuts.set(action, wanted.clone()))?;
    app.state::<crate::ShellMenu>()
        .reflect_shortcuts(&app)
        .map_err(|e| e.to_string())?;
    Ok(wanted)
}

#[cfg(test)]
mod tests {
    use super::{view, Action};

    #[test]
    fn menus_follow_registered_custom_shortcuts_and_hide_unavailable_ones() {
        let wanted = "Ctrl+Shift+K".to_owned();
        for action in [Action::OpenConsole, Action::QuickAsk, Action::ScreenshotChat] {
            assert_eq!(
                view(Some(&wanted), Some(&wanted), action).menu_accelerator(),
                Some(wanted.as_str())
            );
            assert_eq!(view(Some(&wanted), None, action).menu_accelerator(), None);
            assert_eq!(view(None, None, action).menu_accelerator(), None);
        }
    }

    #[test]
    fn a_binding_another_application_took_is_named_as_a_problem() {
        let wanted = "Alt+Space".to_owned();
        assert!(view(Some(&wanted), None, Action::QuickAsk).problem.is_some());
        assert!(view(Some(&wanted), Some(&wanted), Action::QuickAsk).problem.is_none());
        assert!(view(None, None, Action::QuickAsk).problem.is_none());
    }

    #[test]
    fn an_action_is_spelled_the_way_the_console_sends_it() {
        assert_eq!(serde_json::to_string(&Action::QuickAsk).unwrap(), r#""quick_ask""#);
        assert_eq!(
            serde_json::from_str::<Action>(r#""screenshot_chat""#).unwrap(),
            Action::ScreenshotChat
        );
    }
}
