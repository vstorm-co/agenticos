// Every command the app defines, declared so Tauri checks each one against a
// capability: the onboarding page is granted its own, and the console - a remote
// page - only the lock's, the live activities', what was shared and the
// widget's (`grant_console`).
fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "server_url",
            "pair_with",
            "connect",
            "unlock",
            "take_activity_action",
            "take_shared",
            "attach_sheet",
            "offer_recent_photo",
            "show_activity",
            "end_activity",
            "update_widget",
        ]),
    ))
    .expect("failed to run tauri-build");
}
