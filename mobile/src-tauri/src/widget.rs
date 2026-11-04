//! The home-screen widget (#2097): approvals waiting and runs in flight, as
//! the console last counted them. The app holds no session of its own, so the
//! console sends the counts it already reads; the widget shows when they were
//! counted. Android's half is `GlanceWidget.kt`; iOS's is `WidgetPlugin.swift`,
//! read by the widget extension.

use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
#[cfg(mobile)]
use tauri::Manager;
use tauri::{AppHandle, Runtime};

/// What the widget shows.
#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct Glance {
    pub approvals: u32,
    pub running: u32,
    /// Percent of the organization's monthly cap left; absent with no cap.
    #[serde(default)]
    pub budget_left: Option<u8>,
}

#[cfg(mobile)]
struct Native<R: Runtime>(tauri::plugin::PluginHandle<R>);

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_widget);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("widget")
        .setup(|app, api| {
            #[cfg(target_os = "android")]
            app.manage(Native(
                api.register_android_plugin("co.vstorm.agenticos", "WidgetPlugin")?,
            ));
            #[cfg(target_os = "ios")]
            app.manage(Native(api.register_ios_plugin(init_plugin_widget)?));
            #[cfg(not(mobile))]
            let _ = (app, api);
            Ok(())
        })
        .build()
}

/// Keep the counts for the widget and redraw it.
#[tauri::command]
pub fn update_widget<R: Runtime>(app: AppHandle<R>, glance: Glance) -> Result<(), String> {
    #[cfg(mobile)]
    {
        let native = app
            .try_state::<Native<R>>()
            .ok_or("The widget is not set up.")?;
        native
            .0
            .run_mobile_plugin::<serde::de::IgnoredAny>("update", glance)
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
    #[cfg(not(mobile))]
    {
        let _ = (app, glance);
        Ok(())
    }
}

pub fn clear<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    #[cfg(mobile)]
    return app
        .try_state::<Native<R>>()
        .ok_or("The widget is not set up.")?
        .0
        .run_mobile_plugin::<serde::de::IgnoredAny>("clear", ())
        .map(|_| ())
        .map_err(|e| e.to_string());
    #[cfg(not(mobile))]
    {
        let _ = app;
        Ok(())
    }
}
