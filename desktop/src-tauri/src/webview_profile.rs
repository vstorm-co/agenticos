use tauri::{Manager, Runtime, WebviewUrl, WebviewWindowBuilder};

/// One persistent browser profile for the console and its companion windows.
/// Native agent browser tabs deliberately use their own incognito stores.
pub fn window<'a, R: Runtime, M: Manager<R>>(
    manager: &'a M,
    label: &str,
    url: WebviewUrl,
) -> tauri::Result<WebviewWindowBuilder<'a, R, M>> {
    let builder = WebviewWindowBuilder::new(manager, label, url).incognito(false);
    #[cfg(target_os = "macos")]
    // Keep this identifier stable across builds: changing it starts a new cookie jar.
    let builder = builder.data_store_identifier(*b"agenticosconsole");
    #[cfg(not(target_os = "macos"))]
    let builder = builder.data_directory(
        manager
            .app_handle()
            .path()
            .app_local_data_dir()?
            .join("console-webview"),
    );
    Ok(builder)
}
