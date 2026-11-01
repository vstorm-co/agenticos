//! Native lifecycle covers must appear before the OS captures a task preview;
//! a queued webview evaluation on resume is too late to protect that snapshot.

use tauri::plugin::{Builder, TauriPlugin};
#[cfg(target_os = "ios")]
use tauri::Manager;
use tauri::Runtime;

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_app_privacy);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("app-privacy")
        .setup(|_app, _api| {
            #[cfg(target_os = "ios")]
            _app.manage(_api.register_ios_plugin(init_plugin_app_privacy)?);
            Ok(())
        })
        .build()
}
