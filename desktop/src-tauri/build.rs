// Every command the shell defines, declared so that Tauri checks each one
// against a capability. Without this list the shell's own pages may call any
// command and a remote page none; with it, each window - local or the
// console's - is granted exactly the commands it uses, in `capabilities/` and
// in `console::GRANTS`.
const COMMANDS: &[&str] = &[
    "server_url",
    "startup_notice",
    "connect",
    "page_error",
    "show_console",
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
    "onboarding_state",
    "local_status",
    "set_up_local",
    "use_local",
    "open_docker_download",
    "finish_onboarding",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
