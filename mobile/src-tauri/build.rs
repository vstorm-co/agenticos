// Every command the app defines, declared so Tauri checks each one against a
// capability: the onboarding page is granted exactly these, and the console - a
// remote page - none.
fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["server_url", "pair_with", "connect", "unlock"]),
    ))
    .expect("failed to run tauri-build");
}
