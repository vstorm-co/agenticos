//! "Share → AgenticOS" (#2097): what another app shared with this one, held by
//! the native half until the console takes it into a new message.
//!
//! Android's half is `ShareTargetPlugin.kt`, which reads the shared content
//! where its read grant lives; on iOS the share extension copies it into the
//! App Group's inbox and `ShareTargetPlugin.swift` reads it from there.
//!
//! The composer's pickers and the offer of a photo just taken (`AttachPlugin`,
//! in Kotlin and Swift) answer in the same shape: the phone draws them, and the
//! console - a page of a server - is handed only what the person tapped.

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(mobile)]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

/// Text and files another app shared, as the console reads them.
#[derive(Serialize, Deserialize, Default, Debug, PartialEq)]
#[serde(default, rename_all = "camelCase")]
pub struct Shared {
    pub text: String,
    pub files: Vec<SharedFile>,
    /// Files that could not be carried over - too large, or unreadable - by
    /// name, for the console to say so.
    pub refused: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SharedFile {
    pub name: String,
    pub mime_type: String,
    /// The file's bytes, base64.
    pub data: String,
}

#[cfg(any(mobile, test))]
impl Shared {
    fn is_empty(&self) -> bool {
        self.text.is_empty() && self.files.is_empty() && self.refused.is_empty()
    }
}

#[cfg(mobile)]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(mobile)]
struct Attach<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_share_target);
#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_attach);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("share-target")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(api.register_android_plugin(
                "co.vstorm.agenticos",
                "ShareTargetPlugin",
            )?));
            #[cfg(target_os = "ios")]
            app.manage(Native(api.register_ios_plugin(init_plugin_share_target)?));
            #[cfg(not(mobile))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

/// Each native class needs its own plugin id. Registering two classes through
/// one PluginApi replaces the first class in the native command dispatcher.
pub fn attach<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("attach")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Attach(
                api.register_android_plugin("co.vstorm.agenticos", "AttachPlugin")?,
            ));
            #[cfg(target_os = "ios")]
            app.manage(Attach(api.register_ios_plugin(init_plugin_attach)?));
            #[cfg(not(mobile))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

/// What was shared since the last time, taken once; `None` when nothing was.
#[cfg(mobile)]
pub fn take<R: Runtime>(app: &AppHandle<R>) -> Result<Option<Shared>, String> {
    let native = app
        .try_state::<Native<R>>()
        .ok_or("Sharing is not set up.")?;
    let shared: Shared = native
        .0
        .run_mobile_plugin("take", ())
        .map_err(|e| e.to_string())?;
    Ok((!shared.is_empty()).then_some(shared))
}

#[cfg(not(mobile))]
pub fn take<R: Runtime>(_app: &AppHandle<R>) -> Result<Option<Shared>, String> {
    Ok(None)
}

/// Where the person wants a file from: the tile they tapped in the console's
/// sheet. iOS opens that picker at once; Android's sheet offers all three.
#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    Camera,
    Photos,
    Files,
}

#[cfg(mobile)]
#[derive(Serialize)]
struct AskArgs {
    source: Option<Source>,
}

/// What the attach sheet or the offer handed back, once the person answered.
/// Blocks until then - call it off the main thread.
#[cfg(mobile)]
pub fn ask<R: Runtime>(
    app: &AppHandle<R>,
    command: &str,
    source: Option<Source>,
) -> Result<Option<Shared>, String> {
    let native = app
        .try_state::<Attach<R>>()
        .ok_or("Attaching is not set up.")?;
    let chosen: Shared = native
        .0
        .run_mobile_plugin(command, AskArgs { source })
        .map_err(|e| e.to_string())?;
    Ok((!chosen.is_empty()).then_some(chosen))
}

#[cfg(not(mobile))]
pub fn ask<R: Runtime>(
    _app: &AppHandle<R>,
    _command: &str,
    _source: Option<Source>,
) -> Result<Option<Shared>, String> {
    Ok(None)
}

#[cfg(test)]
mod tests {
    use super::{Shared, Source};
    use tauri::plugin::Plugin;

    #[test]
    fn sharing_and_picking_use_distinct_native_dispatchers() {
        let sharing = super::init::<tauri::Wry>();
        let picking = super::attach::<tauri::Wry>();
        assert_eq!(sharing.name(), "share-target");
        assert_eq!(picking.name(), "attach");
        assert_ne!(sharing.name(), picking.name());
    }

    #[test]
    fn nothing_shared_reads_as_empty_and_a_share_in_the_shape_kotlin_sends() {
        let none: Shared = serde_json::from_str("{}").unwrap();
        assert!(none.is_empty());
        let raw = r#"{"text":"look","files":[{"name":"a.png","mimeType":"image/png","data":"iVBO"}],"refused":["big.mov"]}"#;
        let shared: Shared = serde_json::from_str(raw).unwrap();
        assert!(!shared.is_empty());
        assert_eq!(shared.files[0].mime_type, "image/png");
        assert_eq!(shared.refused, vec!["big.mov".to_owned()]);
    }

    #[test]
    fn a_source_is_read_as_the_console_names_it() {
        let source: Source = serde_json::from_str(r#""camera""#).unwrap();
        assert_eq!(source, Source::Camera);
        assert!(serde_json::from_str::<Source>(r#""gallery""#).is_err());
    }
}
