// Every command the app defines, declared so Tauri checks each one against a
// capability: the onboarding page is granted its own, and the console - a remote
// page - only the lock's, the live activities', what was shared and the
// widget's (`grant_console`).
fn main() {
    let mut attributes =
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&[
            "oauth_verifier",
            "server_url",
            "mobile_settings",
            "mobile_servers",
            "bind_push_session",
            "clear_push_session",
            "open_mobile_settings",
            "set_mobile_lock",
            "forget_server",
            "choose_server",
            "startup_notice",
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
            "pin_shortcut",
            "push_status",
            "push_register",
            "push_unregister",
            "apns_status",
            "apns_register",
            "apns_unregister",
        ]));
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
        && std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc")
    {
        // Windows host contract tests create mock WebViews too. Embed the same
        // Common Controls v6 activation context into the library test harness,
        // which Tauri's executable-only resource manifest does not reach.
        attributes = attributes
            .windows_attributes(tauri_build::WindowsAttributes::new_without_app_manifest());
        let manifest = std::path::PathBuf::from(
            std::env::var_os("CARGO_MANIFEST_DIR").expect("Cargo sets its manifest directory"),
        )
        .join("windows-app-manifest.xml");
        println!("cargo:rerun-if-changed={}", manifest.display());
        println!("cargo:rustc-link-arg=/MANIFEST:EMBED");
        println!("cargo:rustc-link-arg=/MANIFESTINPUT:{}", manifest.display());
    }
    tauri_build::try_build(attributes).expect("failed to run tauri-build");
    #[cfg(target_os = "macos")]
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("ios") {
        link_swift_plugins();
    }
}

/// The app's own iOS plugins (`ios/`, a Swift package depending on Tauri's):
/// Tauri's Swift package is copied beside it, where `Package.swift` looks for
/// it, and the package is built and linked into this library - the steps
/// `tauri-plugin`'s build helper takes for a plugin crate, which an app has no
/// helper for.
#[cfg(target_os = "macos")]
fn link_swift_plugins() {
    use std::path::{Path, PathBuf};

    fn copy(from: &Path, to: &Path) -> std::io::Result<()> {
        std::fs::create_dir_all(to)?;
        for entry in std::fs::read_dir(from)? {
            let entry = entry?;
            let name = entry.file_name();
            if [".build", "Package.resolved", "Tests"].contains(&name.to_string_lossy().as_ref()) {
                continue;
            }
            if entry.file_type()?.is_dir() {
                copy(&entry.path(), &to.join(&name))?;
            } else {
                std::fs::copy(entry.path(), to.join(&name))?;
            }
        }
        Ok(())
    }

    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("set by cargo"));
    let tauri_api = std::env::var("DEP_TAURI_IOS_LIBRARY_PATH")
        .expect("tauri announces its Swift package to the crates that depend on it");
    let target = manifest.join(".tauri").join("tauri-api");
    let _ = std::fs::remove_dir_all(&target);
    copy(Path::new(&tauri_api), &target).expect("could not copy Tauri's Swift package");
    println!("cargo:rerun-if-changed=ios/Sources");
    println!("cargo:rerun-if-changed=ios/Package.swift");
    tauri_utils::build::link_apple_library("agenticos-native", manifest.join("ios"));
}
