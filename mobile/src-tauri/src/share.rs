//! "Share → AgenticOS" (#2097): what another app shared with this one, held by
//! the native half until the console takes it into a new message.
//!
//! Android's half is `ShareTargetPlugin.kt`, which reads the shared content
//! where its read grant lives; the iOS share extension needs the Xcode project.
//!
//! The composer's attach sheet and the offer of a photo just taken
//! (`AttachPlugin.kt`) answer in the same shape: the phone draws them, and the
//! console - a page of a server - is handed only what the person tapped.

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(target_os = "android")]
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

#[cfg(any(target_os = "android", test))]
impl Shared {
    fn is_empty(&self) -> bool {
        self.text.is_empty() && self.files.is_empty() && self.refused.is_empty()
    }
}

#[cfg(target_os = "android")]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "android")]
struct Attach<R: Runtime>(tauri::plugin::PluginHandle<R>);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("share-target")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(api.register_android_plugin(
                "co.vstorm.agenticos",
                "ShareTargetPlugin",
            )?));
            #[cfg(target_os = "android")]
            app.manage(Attach(
                api.register_android_plugin("co.vstorm.agenticos", "AttachPlugin")?,
            ));
            #[cfg(not(target_os = "android"))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

/// What was shared since the last time, taken once; `None` when nothing was.
#[cfg(target_os = "android")]
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

#[cfg(not(target_os = "android"))]
pub fn take<R: Runtime>(_app: &AppHandle<R>) -> Result<Option<Shared>, String> {
    Ok(None)
}

/// What the attach sheet or the offer handed back, once the person answered.
/// Blocks until then - call it off the main thread.
#[cfg(target_os = "android")]
pub fn ask<R: Runtime>(app: &AppHandle<R>, command: &str) -> Result<Option<Shared>, String> {
    let native = app
        .try_state::<Attach<R>>()
        .ok_or("Attaching is not set up.")?;
    let chosen: Shared = native
        .0
        .run_mobile_plugin(command, ())
        .map_err(|e| e.to_string())?;
    Ok((!chosen.is_empty()).then_some(chosen))
}

#[cfg(not(target_os = "android"))]
pub fn ask<R: Runtime>(_app: &AppHandle<R>, _command: &str) -> Result<Option<Shared>, String> {
    Ok(None)
}

#[cfg(test)]
mod tests {
    use super::Shared;

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
}
