//! Download the official platform installer only after an explicit setup action.
use tauri::AppHandle;
#[cfg(target_os = "macos")]
use tauri::{Emitter, Manager};
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
        app.opener()
            .open_path(destination.to_string_lossy(), None::<&str>)
            .map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn open_docker(app: AppHandle) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let _ = app;
        tauri::async_runtime::spawn_blocking(|| {
            let result = std::process::Command::new("/usr/bin/open")
                .args(["-a", "Docker"])
                .status()
                .map_err(|e| e.to_string())?;
            if result.success() {
                Ok(())
            } else {
                Err("Install Docker Desktop in Applications, then try again.".into())
            }
        })
        .await
        .map_err(|e| e.to_string())?
    }
    #[cfg(not(target_os = "macos"))]
    app.opener()
        .open_url(crate::local_stack::docker_download(), None::<&str>)
        .map_err(|e| e.to_string())
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
    fn empty_and_truncated_installers_are_not_opened() {
        assert!(completed(0, None).is_err());
        assert!(completed(9, Some(10)).is_err());
        assert!(completed(10, Some(10)).is_ok());
        assert!(completed(10, None).is_ok());
    }
}
