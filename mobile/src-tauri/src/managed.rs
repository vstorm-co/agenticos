//! The organization's device management (#2097): Android's managed
//! configuration - `serverUrl`, `serverLocked`, `biometricLock` - read through
//! `ManagedConfigPlugin.kt`. The rules are the shared crate's
//! `ManagedPolicy`; on iOS the same keys come as managed app configuration
//! (AppConfig), read by `ManagedConfigPlugin.swift`.

use agenticos_shell_core::ManagedPolicy;
use serde::Deserialize;
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(mobile)]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

#[derive(Deserialize, Default, Debug, PartialEq)]
#[serde(default, rename_all = "camelCase")]
struct Raw {
    server_url: Option<String>,
    server_locked: bool,
    /// `person`, `on` or `off`.
    biometric_lock: Option<String>,
}

fn policy(raw: Raw, lan_http: bool) -> Result<ManagedPolicy, String> {
    let lock = match raw.biometric_lock.as_deref() {
        Some("on") => Some(true),
        Some("off") => Some(false),
        _ => None,
    };
    ManagedPolicy::new(raw.server_url.as_deref(), raw.server_locked, lock, lan_http)
}

#[cfg(mobile)]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_managed_config);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("managed-config")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(api.register_android_plugin(
                "co.vstorm.agenticos",
                "ManagedConfigPlugin",
            )?));
            #[cfg(target_os = "ios")]
            app.manage(Native(api.register_ios_plugin(init_plugin_managed_config)?));
            #[cfg(not(mobile))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

/// The policy in force. One that cannot be read is said and ignored: a broken
/// policy must not lock anybody out of the app.
pub fn load<R: Runtime>(app: &AppHandle<R>, lan_http: bool) -> ManagedPolicy {
    #[cfg(mobile)]
    let raw = app
        .try_state::<Native<R>>()
        .ok_or_else(|| "Managed configuration is not set up.".to_owned())
        .and_then(|native| {
            native
                .0
                .run_mobile_plugin::<Raw>("read", ())
                .map_err(|e| e.to_string())
        });
    #[cfg(not(mobile))]
    let raw: Result<Raw, String> = {
        let _ = app;
        Ok(Raw::default())
    };
    raw.and_then(|raw| policy(raw, lan_http))
        .unwrap_or_else(|e| {
            eprintln!("managed configuration: {e}");
            ManagedPolicy::default()
        })
}

#[cfg(test)]
mod tests {
    use super::{policy, Raw};

    #[test]
    fn an_emm_sets_the_server_the_lock_and_the_biometrics() {
        let raw: Raw = serde_json::from_str(
            r#"{"serverUrl":"agenticos.acme.com","serverLocked":true,"biometricLock":"on"}"#,
        )
        .unwrap();
        let managed = policy(raw, false).unwrap();
        assert!(managed.server_locked);
        assert_eq!(managed.biometric_lock, Some(true));
        let off: Raw = serde_json::from_str(r#"{"biometricLock":"off"}"#).unwrap();
        assert_eq!(policy(off, false).unwrap().biometric_lock, Some(false));
        let unset = policy(Raw::default(), false).unwrap();
        assert_eq!(unset.biometric_lock, None);
        assert!(unset.server.is_none());
    }
}
