//! Prepare the local runtime after an explicit setup action; macOS owns elevation and first-run prompts.
use tauri::AppHandle;
#[cfg(target_os = "macos")]
use tauri::{Emitter, Manager};
#[cfg(not(target_os = "macos"))]
use tauri_plugin_opener::OpenerExt;

#[cfg(target_os = "macos")]
static DOWNLOAD: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[cfg(target_os = "macos")]
fn installer_url() -> &'static str {
    if cfg!(target_arch = "aarch64") {
        "https://desktop.docker.com/mac/main/arm64/Docker.dmg"
    } else {
        "https://desktop.docker.com/mac/main/amd64/Docker.dmg"
    }
}

#[cfg(target_os = "macos")]
fn allowed_redirect(url: &tauri::Url, previous: usize) -> bool {
    previous < 5 && url.scheme() == "https" && url.host_str() == Some("desktop.docker.com")
}
#[cfg(target_os = "macos")]
fn completed(received: u64, total: Option<u64>) -> Result<(), String> {
    if received == 0 || total.is_some_and(|length| received != length) {
        Err("Docker installer download was incomplete.".into())
    } else {
        Ok(())
    }
}

#[tauri::command]
pub async fn download_docker(app: AppHandle) -> Result<(), String> {
    #[cfg(not(target_os = "macos"))]
    return app
        .opener()
        .open_url(crate::local_stack::docker_download(), None::<&str>)
        .map_err(|e| e.to_string());
    #[cfg(target_os = "macos")]
    {
        use tokio::io::AsyncWriteExt;
        let _download = DOWNLOAD
            .try_lock()
            .map_err(|_| "A Docker download is already in progress.")?;
        if crate::docker_runtime::desktop_app().is_some() {
            return tauri::async_runtime::spawn_blocking(crate::docker_runtime::ensure_running)
                .await
                .map_err(|e| e.to_string())?;
        }
        let dir = app
            .path()
            .app_cache_dir()
            .map_err(|e| e.to_string())?
            .join("installers");
        tokio::fs::create_dir_all(&dir).await.map_err(|e| e.to_string())?;
        let part = dir.join("Docker.dmg.part");
        let destination = dir.join("Docker.dmg");
        // A second click must not truncate an in-flight installer.
        let mut file = tokio::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&part)
            .await
            .map_err(|_| "The app could not create the Docker installer in its cache.".to_string())?;
        let download = async {
            let client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(1800))
                .connect_timeout(std::time::Duration::from_secs(20))
                .redirect(reqwest::redirect::Policy::custom(|attempt| {
                    if allowed_redirect(attempt.url(), attempt.previous().len()) {
                        attempt.follow()
                    } else {
                        attempt.error("Docker installer redirected outside its official download host")
                    }
                }))
                .build()
                .map_err(|e| e.to_string())?;
            let mut response = client
                .get(installer_url())
                .send()
                .await
                .and_then(reqwest::Response::error_for_status)
                .map_err(|e| format!("Cannot download Docker: {e}"))?;
            let total = response.content_length();
            let mut received: u64 = 0;
            let mut last = std::time::Instant::now();
            while let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? {
                received += chunk.len() as u64;
                if received > 5 * 1024 * 1024 * 1024 {
                    return Err("Docker installer exceeded the download limit.".to_string());
                }
                file.write_all(&chunk).await.map_err(|e| e.to_string())?;
                if last.elapsed() > std::time::Duration::from_millis(250) {
                    app.emit_to(
                        crate::WINDOW,
                        "docker:download",
                        serde_json::json!({"received":received,"total":total}),
                    )
                    .map_err(|e| e.to_string())?;
                    last = std::time::Instant::now();
                }
            }
            completed(received, total)?;
            file.flush().await.map_err(|e| e.to_string())?;
            Ok(())
        }
        .await;
        drop(file);
        if let Err(error) = download {
            let _ = tokio::fs::remove_file(&part).await;
            return Err(error);
        }
        tokio::fs::rename(&part, &destination)
            .await
            .map_err(|e| e.to_string())?;
        // Preserve macOS's downloaded-software checks when the installer is opened.
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_secs();
        let quarantine = format!("0081;{stamp:x};AgenticOS;");
        let marked = tokio::process::Command::new("/usr/bin/xattr")
            .args(["-w", "com.apple.quarantine", &quarantine])
            .arg(&destination)
            .status()
            .await
            .map_err(|e| e.to_string())?;
        if !marked.success() {
            return Err("Cannot apply macOS installer safety checks to the download.".into());
        }
        app.emit_to(
            crate::WINDOW,
            "docker:download",
            serde_json::json!({"message":"Installing local runtime… Approve the system installation prompt."}),
        )
        .map_err(|e| e.to_string())?;
        install_macos(&app, &destination).await?;
        app.emit_to(crate::WINDOW, "docker:download", serde_json::json!({"message":"Starting local runtime… Complete any first-run prompts; AgenticOS will continue automatically."})).map_err(|e| e.to_string())?;
        tauri::async_runtime::spawn_blocking(crate::docker_runtime::ensure_running)
            .await
            .map_err(|e| e.to_string())?
    }
}

#[tauri::command]
pub async fn open_docker(app: AppHandle) -> Result<(), String> {
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    {
        let _ = app;
        tauri::async_runtime::spawn_blocking(crate::docker_runtime::ensure_running)
            .await
            .map_err(|e| e.to_string())?
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let _ = app;
        Err("Start your container engine, then choose Check again to continue.".into())
    }
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
    #[test]
    fn installer_redirects_stay_on_the_official_tls_host() {
        assert!(allowed_redirect(
            &tauri::Url::parse("https://desktop.docker.com/mac/main/arm64/Docker.dmg").unwrap(),
            1
        ));
        for url in [
            "http://desktop.docker.com/Docker.dmg",
            "https://outside.example/Docker.dmg",
        ] {
            assert!(!allowed_redirect(&tauri::Url::parse(url).unwrap(), 1));
        }
        assert!(!allowed_redirect(
            &tauri::Url::parse("https://desktop.docker.com/Docker.dmg").unwrap(),
            5
        ));
    }
    #[test]
    fn installation_paths_are_quoted_for_applescript_and_the_shell() {
        let path = std::path::Path::new("/tmp/User's \"folder\"/$HOME/installer");
        let script = installer_script(path);
        let expression = script
            .strip_prefix("do shell script ")
            .unwrap()
            .strip_suffix(" with administrator privileges")
            .unwrap();
        let output = std::process::Command::new("/usr/bin/osascript")
            .args(["-e", &format!("return {expression}")])
            .output()
            .unwrap();
        assert!(output.status.success());
        let shell = String::from_utf8(output.stdout).unwrap();
        let output = std::process::Command::new("/bin/sh")
            .args(["-c", &format!("printf %s {}", shell.trim_end())])
            .output()
            .unwrap();
        assert!(output.status.success());
        assert_eq!(String::from_utf8(output.stdout).unwrap(), path.to_string_lossy());
        assert!(!script.contains("accept-license"));
    }
    #[tokio::test]
    async fn installer_failures_are_not_reported_as_success() {
        assert!(
            system_command(tokio::process::Command::new("/usr/bin/false"), "test installation")
                .await
                .is_err()
        );
        assert!(
            system_command(tokio::process::Command::new("/usr/bin/true"), "test installation")
                .await
                .is_ok()
        );
    }
    #[test]
    fn empty_and_truncated_installers_are_not_opened() {
        assert!(completed(0, None).is_err());
        assert!(completed(9, Some(10)).is_err());
        assert!(completed(10, Some(10)).is_ok());
        assert!(completed(10, None).is_ok());
    }
}

#[cfg(target_os = "macos")]
async fn system_command(mut command: tokio::process::Command, action: &str) -> Result<(), String> {
    command.kill_on_drop(true);
    let output = tokio::time::timeout(std::time::Duration::from_secs(600), command.output())
        .await
        .map_err(|_| format!("Timed out while {action}. Retry preparing this computer."))?
        .map_err(|error| format!("Could not {action}: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Could not {action}. Complete any system prompts, then retry preparing this computer."
        ))
    }
}

#[cfg(target_os = "macos")]
fn installer_script(installer: &std::path::Path) -> String {
    // Quote for both interpreters: paths are data, even with apostrophes or quotes.
    let shell = format!("'{}'", installer.to_string_lossy().replace('\'', "'\"'\"'"));
    format!(
        "do shell script \"{}\" with administrator privileges",
        shell.replace('\\', "\\\\").replace('\"', "\\\"")
    )
}

#[cfg(target_os = "macos")]
async fn install_macos(app: &AppHandle, image: &std::path::Path) -> Result<(), String> {
    let mount = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join(format!("docker-install-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&mount).await.map_err(|e| e.to_string())?;
    let mut attach = tokio::process::Command::new("/usr/bin/hdiutil");
    attach
        .args(["attach", "-readonly", "-nobrowse", "-mountpoint"])
        .arg(&mount)
        .arg(image);
    let mounted = system_command(attach, "open the local runtime installer").await;
    if let Err(error) = mounted {
        let _ = tokio::fs::remove_dir(&mount).await;
        return Err(error);
    }
    let result = async {
        let bundle = mount.join("Docker.app");
        let mut assess = tokio::process::Command::new("/usr/sbin/spctl");
        assess.args(["--assess", "--type", "execute"]).arg(&bundle);
        system_command(assess, "verify the local runtime installer").await?;
        let mut install = tokio::process::Command::new("/usr/bin/osascript");
        install
            .arg("-e")
            .arg(installer_script(&bundle.join("Contents/MacOS/install")));
        system_command(install, "install the local runtime").await
    }
    .await;
    let mut detach = tokio::process::Command::new("/usr/bin/hdiutil");
    detach.arg("detach").arg(&mount);
    let detached = system_command(detach, "close the local runtime installer").await;
    if detached.is_ok() {
        let _ = tokio::fs::remove_dir(&mount).await;
    }
    match (result, detached) {
        (Err(error), Err(cleanup)) => Err(format!("{error} {cleanup}")),
        (Err(error), _) | (_, Err(error)) => Err(error),
        _ => Ok(()),
    }
}
