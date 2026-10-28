// Every command the shell defines, declared so that Tauri checks each one
// against a capability. Without this list the shell's own pages may call any
// command and a remote page none; with it, each window - local or the
// console's - is granted exactly the commands it uses, in `capabilities/` and
// in `console::GRANTS`.
const COMMANDS: &[&str] = &[
    "native_browser_view",
    "native_browser_input",
    "server_url",
    "startup_notice",
    "connect",
    "page_error",
    "show_console",
    "change_server",
    "open_chat",
    "desktop_state",
    "set_appearance",
    "set_blobby",
    "save_blobby_position",
    "resize_blobby",
    "blobby_menu",
    "set_window_preferences",
    "notify",
    "set_badge",
    "open_in_console",
    "set_shortcut",
    "resize_quick_ask",
    "hide_quick_ask",
    "take_context_files",
    "open_accessibility_settings",
    "take_shared",
    "pin_agent",
    "unpin_agent",
    "onboarding_state",
    "onboarding_permissions",
    "request_onboarding_permission",
    "local_status",
    "set_up_local",
    "use_local",
    "open_docker_download",
    "finish_onboarding",
    "device_status",
    "device_link",
    "device_unlink",
    "local_grants",
    "local_pick_folder",
    "local_revoke",
    "local_files",
    "local_file",
    "local_services",
    "local_save_service",
    "local_remove_service",
];

fn main() {
    let mut attributes =
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(COMMANDS));
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
        && std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc")
    {
        // Tauri's resource manifest reaches binaries, but not the library test
        // harness. Mock windows also link Common Controls v6: without a manifest
        // those tests fail in the Windows loader before any test can run.
        // Use the same linker-based embedding as Tauri's own API example:
        // https://github.com/tauri-apps/tauri/blob/dev/examples/api/src-tauri/build.rs
        attributes = attributes.windows_attributes(tauri_build::WindowsAttributes::new_without_app_manifest());
        let manifest = std::path::PathBuf::from(
            std::env::var_os("CARGO_MANIFEST_DIR").expect("Cargo sets its manifest directory"),
        )
        .join("windows-app-manifest.xml");
        println!("cargo:rerun-if-changed={}", manifest.display());
        println!("cargo:rustc-link-arg=/MANIFEST:EMBED");
        println!("cargo:rustc-link-arg=/MANIFESTINPUT:{}", manifest.display());
    }
    tauri_build::try_build(attributes).expect("failed to run tauri-build");
}
