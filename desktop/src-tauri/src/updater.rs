//! Updates are signed by the distributor and installed only after native consent.

use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

const WORKSPACE_UPDATE_HELP: &str = "Local workspaces update separately: choose Update local workspace… in the AgenticOS app menu (macOS) or the tray menu.";

pub fn configured() -> bool {
    option_env!("AGENTICOS_UPDATER_PUBLIC_KEY").is_some_and(|key| !key.trim().is_empty())
}

pub async fn check(app: AppHandle) -> Result<(), String> {
    if cfg!(all(target_os = "linux", feature = "arch-package")) {
        app.dialog()
            .message(format!("This desktop installation is managed by pacman. Download the latest Arch package from AgenticOS GitHub releases and upgrade it with sudo pacman -U. The app does not replace package-managed files. {WORKSPACE_UPDATE_HELP}"))
            .title("Update with pacman")
            .show(|_| {});
        return Ok(());
    }
    if !configured() {
        app.dialog()
            .message(
                format!("This desktop build has no update signing key. Download a newer installer from the AgenticOS GitHub releases. {WORKSPACE_UPDATE_HELP}"),
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
            .message(format!("You are using the latest desktop app. {WORKSPACE_UPDATE_HELP}"))
            .title("Up to date")
            .show(|_| {});
        return Ok(());
    };
    let (send, receive) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(format!(
            "Desktop app {} is available. Install it and restart the app? Finish any local work first. Your local workspace updates separately: after restarting, choose Update local workspace… in the AgenticOS app menu (macOS) or the tray menu.",
            update.version
        ))
        .title("Update desktop app?")
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
