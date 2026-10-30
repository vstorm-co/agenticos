//! Live activities: what an agent is doing, drawn by the phone itself - the
//! Dynamic Island and the lock screen on iOS, an ongoing notification on
//! Android - while the app is in the background (#2097).
//!
//! The console decides what is live, from the reads it already makes, and says
//! so through `show_activity` and `end_activity`. The native half draws it;
//! its buttons come back as `agenticos://activity/...` links (`activity_link`).

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(mobile)]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

use agenticos_shell_core::is_console_path;

/// One live activity, as the console describes it.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LiveActivity {
    /// Stable for the thing it is about - `run:<id>`, `approval:<id>` - so a
    /// second `show` updates the first rather than stacking another.
    pub id: String,
    pub kind: Kind,
    pub title: String,
    pub body: String,
    /// The console page a tap on it opens.
    pub path: String,
    /// Milliseconds since the epoch, for a clock that counts up on its own.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub started_at: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub approval_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub approve_label: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reject_label: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Run,
    Approval,
    /// An agent's question waiting on the person's answer.
    Question,
    /// A voice call in progress, with its clock.
    Call,
}

const MAX_TEXT: usize = 300;
const MAX_ID: usize = 120;

/// Check what a page sends before the system draws it on the lock screen.
pub fn validate(activity: &LiveActivity) -> Result<(), String> {
    let sized = |value: &str, max: usize| !value.trim().is_empty() && value.chars().count() <= max;
    if !sized(&activity.id, MAX_ID)
        || !sized(&activity.title, MAX_TEXT)
        || activity.body.chars().count() > MAX_TEXT
    {
        return Err("A live activity needs an id and a title, and short text.".to_owned());
    }
    if !is_console_path(&activity.path) {
        return Err(format!("{} is not a page of the console.", activity.path));
    }
    let names_approval = activity
        .approval_id
        .as_deref()
        .is_some_and(|id| !id.trim().is_empty());
    if activity.kind == Kind::Approval && !names_approval {
        return Err("An approval's activity names the approval.".to_owned());
    }
    Ok(())
}

#[derive(Serialize)]
struct EndPayload<'a> {
    id: &'a str,
}

#[cfg(mobile)]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_live_activity);

/// The plugin holding the native half: Android's `LiveActivityPlugin.kt`, and
/// on iOS `LiveActivityPlugin.swift` (ActivityKit), whose activities the
/// widget extension draws. On a laptop an activity goes nowhere.
pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("live-activity")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(api.register_android_plugin(
                "co.vstorm.agenticos",
                "LiveActivityPlugin",
            )?));
            #[cfg(target_os = "ios")]
            app.manage(Native(api.register_ios_plugin(init_plugin_live_activity)?));
            #[cfg(not(mobile))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

#[cfg(mobile)]
fn run<R: Runtime, T: Serialize>(
    app: &AppHandle<R>,
    command: &str,
    payload: T,
) -> Result<(), String> {
    let native = app
        .try_state::<Native<R>>()
        .ok_or("Live activities are not set up.")?;
    // The Kotlin side resolves with an empty object; nothing in it is read.
    native
        .0
        .run_mobile_plugin::<serde::de::IgnoredAny>(command, payload)
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[cfg(not(mobile))]
fn run<R: Runtime, T: Serialize>(
    _app: &AppHandle<R>,
    _command: &str,
    _payload: T,
) -> Result<(), String> {
    Ok(())
}

/// Start an activity, or update the one with the same id.
#[tauri::command]
pub fn show_activity<R: Runtime>(app: AppHandle<R>, activity: LiveActivity) -> Result<(), String> {
    validate(&activity)?;
    run(&app, "show", activity)
}

/// End an activity: the run finished, the approval was decided.
#[tauri::command]
pub fn end_activity<R: Runtime>(app: AppHandle<R>, id: String) -> Result<(), String> {
    run(&app, "end", EndPayload { id: &id })
}

/// Clear the old server's actions before a different server becomes active.
pub fn clear<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    run(app, "clear", ())
}

#[cfg(test)]
mod tests {
    use super::{validate, Kind, LiveActivity};

    fn approval() -> LiveActivity {
        LiveActivity {
            id: "approval:ap1".into(),
            kind: Kind::Approval,
            title: "Support wants to run send_email".into(),
            body: "to: a@b.c".into(),
            path: "/runs?tab=approvals".into(),
            started_at: None,
            approval_id: Some("ap1".into()),
            approve_label: Some("Approve".into()),
            reject_label: Some("Reject".into()),
        }
    }

    #[test]
    fn an_activity_is_read_in_the_shape_the_console_sends() {
        let raw = r#"{"id":"run:r1","kind":"run","title":"Support is working","body":"","path":"/runs","startedAt":1760000000000}"#;
        let activity: LiveActivity = serde_json::from_str(raw).unwrap();
        assert_eq!(activity.kind, Kind::Run);
        assert_eq!(activity.started_at, Some(1_760_000_000_000));
        assert!(validate(&activity).is_ok());
    }

    #[test]
    fn a_sound_approval_passes_and_a_broken_one_does_not() {
        assert!(validate(&approval()).is_ok());
        for broken in [
            LiveActivity {
                approval_id: None,
                ..approval()
            },
            LiveActivity {
                path: "https://evil.example".into(),
                ..approval()
            },
            LiveActivity {
                approval_id: Some(" ".into()),
                ..approval()
            },
            LiveActivity {
                title: " ".into(),
                ..approval()
            },
            LiveActivity {
                body: "x".repeat(301),
                ..approval()
            },
        ] {
            assert!(validate(&broken).is_err(), "{broken:?}");
        }
    }
}
