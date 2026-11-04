//! Updates are signed by the distributor and installed only after native consent.

use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

pub fn configured() -> bool {
    option_env!("AGENTICOS_UPDATER_PUBLIC_KEY").is_some_and(|key| !key.trim().is_empty())
}

pub async fn check(app: AppHandle) -> Result<(), String> {
    if !configured() {
        app.dialog()
            .message(
                "This build has no update signing key. Download a newer installer from the AgenticOS GitHub releases.",
            )
            .title("Updates unavailable")
            .show(|_| {});
        return Ok(());
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| format!("Could not check for updates: {e}"))?;
    let Some(update) = update else {
        app.dialog()
            .message("You are using the latest version of AgenticOS.")
            .title("Up to date")
            .show(|_| {});
        return Ok(());
    };
    let (send, receive) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(format!(
            "AgenticOS {} is available. Install it and restart the app? Finish any local work first.",
            update.version
        ))
        .title("Update AgenticOS?")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Install and restart".into(),
            "Later".into(),
        ))
        .show(move |allowed| {
            let _ = send.send(allowed);
        });
    if !receive.await.unwrap_or(false) {
        return Ok(());
    }
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|e| format!("Could not install the signed update: {e}"))?;
    app.restart();
}
