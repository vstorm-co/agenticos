//! Push on iPhone (#2097): Apple's push service with the organization's own
//! key, which the server holds (`app/services/apns.py`). The app asks the
//! person, registers with APNs and hands the console the device token for the
//! server. iOS's half is `ApnsPlugin.swift`; Android pushes through UnifiedPush
//! (`push`), so there these answer that APNs is not here.

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(target_os = "ios")]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

/// Where notifications stand on this iPhone.
#[derive(Serialize, Deserialize, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ApnsStatus {
    /// `granted`, `denied` or `undetermined`; `unsupported` off iOS.
    pub permission: String,
    /// The device token, hex, once registered.
    #[serde(default)]
    pub token: Option<String>,
}

impl ApnsStatus {
    #[cfg(not(target_os = "ios"))]
    fn unsupported() -> Self {
        Self {
            permission: "unsupported".to_owned(),
            token: None,
        }
    }
}

#[cfg(target_os = "ios")]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_apns);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("apns")
        .setup(|app, api| {
            #[cfg(target_os = "ios")]
            app.manage(Native(api.register_ios_plugin(init_plugin_apns)?));
            #[cfg(not(target_os = "ios"))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

#[cfg(target_os = "ios")]
fn run<R: Runtime, O: serde::de::DeserializeOwned>(
    app: &AppHandle<R>,
    command: &str,
) -> Result<O, String> {
    let native = app.try_state::<Native<R>>().ok_or("Push is not set up.")?;
    native
        .0
        .run_mobile_plugin(command, ())
        .map_err(|e| e.to_string())
}

/// Whether the person let the app notify, and the token if it has one.
#[tauri::command]
pub async fn apns_status<R: Runtime>(app: AppHandle<R>) -> Result<ApnsStatus, String> {
    #[cfg(target_os = "ios")]
    return tauri::async_runtime::spawn_blocking(move || run(&app, "status"))
        .await
        .map_err(|e| e.to_string())?;
    #[cfg(not(target_os = "ios"))]
    {
        let _ = app;
        Ok(ApnsStatus::unsupported())
    }
}

/// Ask the person, then APNs: the token, or `denied` when the person said no.
#[tauri::command]
pub async fn apns_register<R: Runtime>(app: AppHandle<R>) -> Result<ApnsStatus, String> {
    #[cfg(target_os = "ios")]
    return tauri::async_runtime::spawn_blocking(move || run(&app, "register"))
        .await
        .map_err(|e| e.to_string())?;
    #[cfg(not(target_os = "ios"))]
    {
        let _ = app;
        Ok(ApnsStatus::unsupported())
    }
}

#[tauri::command]
pub async fn apns_unregister<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    #[cfg(target_os = "ios")]
    return tauri::async_runtime::spawn_blocking(move || {
        run::<R, serde::de::IgnoredAny>(&app, "unregister").map(|_| ())
    })
    .await
    .map_err(|e| e.to_string())?;
    #[cfg(not(target_os = "ios"))]
    {
        let _ = app;
        Ok(())
    }
}

#[cfg(target_os = "ios")]
pub fn open_settings<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    run::<R, serde::de::IgnoredAny>(app, "openSettings").map(|_| ())
}

#[cfg(target_os = "ios")]
pub fn bind<R: Runtime>(app: &AppHandle<R>, session_id: &str) -> Result<(), String> {
    let native = app.try_state::<Native<R>>().ok_or("Push is not set up.")?;
    native
        .0
        .run_mobile_plugin::<serde::de::IgnoredAny>(
            "bindSession",
            serde_json::json!({"sessionId": session_id}),
        )
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::ApnsStatus;

    #[test]
    fn a_status_is_read_in_the_shape_swift_sends() {
        let none: ApnsStatus = serde_json::from_str(r#"{"permission":"undetermined"}"#).unwrap();
        assert_eq!(none.token, None);
        let on: ApnsStatus =
            serde_json::from_str(r#"{"permission":"granted","token":"a1b2"}"#).unwrap();
        assert_eq!(on.token.as_deref(), Some("a1b2"));
    }
}
