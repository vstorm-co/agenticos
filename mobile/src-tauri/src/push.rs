//! Push while the app is closed (#2097), through a UnifiedPush distributor -
//! ntfy - rather than Firebase. The distributor hands the app a Web Push
//! endpoint and keys, which the console subscribes with exactly as a browser
//! does. Android's half is `UnifiedPushPlugin.kt` and `PushMessagingService.kt`;
//! iOS gets APNs once there is an Xcode project to sign it with.

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(target_os = "android")]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

/// Where push stands on this phone.
#[derive(Serialize, Deserialize, Default, Debug, PartialEq)]
#[serde(default, rename_all = "camelCase")]
pub struct PushStatus {
    /// Distributor apps installed - none means push needs one (ntfy).
    pub distributors: Vec<String>,
    /// The one in use, once registered.
    pub distributor: Option<String>,
    /// Why the last registration failed, as the connector names it.
    pub failed: Option<String>,
    /// The subscription the distributor handed over, for the server.
    pub endpoint: Option<String>,
    pub p256dh: Option<String>,
    pub auth: Option<String>,
}

#[derive(Serialize)]
struct RegisterArgs<'a> {
    vapid: &'a str,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Registered {
    registered: bool,
}

#[cfg(target_os = "android")]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("unified-push")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(api.register_android_plugin(
                "co.vstorm.agenticos",
                "UnifiedPushPlugin",
            )?));
            #[cfg(not(target_os = "android"))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

#[cfg(target_os = "android")]
fn run<R: Runtime, T: Serialize, O: serde::de::DeserializeOwned>(
    app: &AppHandle<R>,
    command: &str,
    payload: T,
) -> Result<O, String> {
    let native = app.try_state::<Native<R>>().ok_or("Push is not set up.")?;
    native
        .0
        .run_mobile_plugin(command, payload)
        .map_err(|e| e.to_string())
}

#[cfg(not(target_os = "android"))]
fn run<R: Runtime, T: Serialize, O: Default>(
    _app: &AppHandle<R>,
    _command: &str,
    _payload: T,
) -> Result<O, String> {
    Ok(O::default())
}

/// Where push stands: distributors, the one in use, the subscription.
#[tauri::command]
pub async fn push_status<R: Runtime>(app: AppHandle<R>) -> Result<PushStatus, String> {
    tauri::async_runtime::spawn_blocking(move || run(&app, "status", ()))
        .await
        .map_err(|e| e.to_string())?
}

/// Register with the phone's distributor for this deployment's VAPID key. The
/// endpoint arrives a moment later, in `push_status`. Whether a distributor
/// was there to register with.
#[tauri::command]
pub async fn push_register<R: Runtime>(app: AppHandle<R>, vapid: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run::<R, _, Registered>(&app, "register", RegisterArgs { vapid: &vapid })
            .map(|answer| answer.registered)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn push_unregister<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        run::<R, _, serde::de::IgnoredAny>(&app, "unregister", ()).map(|_| ())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::PushStatus;

    #[test]
    fn a_status_is_read_in_the_shape_kotlin_sends() {
        let none: PushStatus = serde_json::from_str(r#"{"distributors":[]}"#).unwrap();
        assert!(none.distributors.is_empty() && none.endpoint.is_none());
        let on: PushStatus = serde_json::from_str(
            r#"{"distributors":["io.heckel.ntfy"],"distributor":"io.heckel.ntfy","endpoint":"https://ntfy.sh/upX","p256dh":"BPk","auth":"c2Vj"}"#,
        )
        .unwrap();
        assert_eq!(on.distributor.as_deref(), Some("io.heckel.ntfy"));
        assert_eq!(on.auth.as_deref(), Some("c2Vj"));
    }
}
