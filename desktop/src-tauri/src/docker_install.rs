//! Prepare the local runtime after an explicit setup action; macOS owns elevation and first-run prompts.
use sha2::{Digest, Sha256};
use std::path::Path;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

static DOWNLOAD: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn allowed_redirect(url: &tauri::Url, previous: usize) -> bool {
    previous < 5 && url.scheme() == "https" && url.host_str() == Some("desktop.docker.com")
}
fn completed(received: u64, total: Option<u64>) -> Result<(), String> {
    if received == 0 || total.is_some_and(|length| received != length) {
        Err("The runtime download was incomplete.".into())
    } else {
        Ok(())
    }
}

async fn checksum(path: &Path) -> Result<String, String> {
    let mut file = tokio::fs::File::open(path).await.map_err(|e| e.to_string())?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer).await.map_err(|e| e.to_string())?;
        if count == 0 {
            return Ok(format!("{:x}", digest.finalize()));
        }
        digest.update(&buffer[..count]);
    }
}

#[tauri::command]
pub async fn download_docker(app: AppHandle) -> Result<(), String> {
    let _download = DOWNLOAD.try_lock().map_err(|_| "Preparation is already running.")?;
    let installed = crate::runtime_installer::installed();
    if installed {
        #[cfg(target_os = "linux")]
        if crate::runtime_installer::ensure_linux_access().await? == crate::runtime_installer::Outcome::RestartRequired
        {
            let pending = crate::runtime_installer::pending_path(&app)?;
            if let Some(parent) = pending.parent() {
                tokio::fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
            }
            tokio::fs::write(pending, "setup").await.map_err(|e| e.to_string())?;
            return Err("Restart your computer and reopen AgenticOS. Setup will continue automatically.".into());
        }
        #[cfg(target_os = "windows")]
        if crate::runtime_installer::ensure_windows_features().await?
            == crate::runtime_installer::Outcome::RestartRequired
        {
            let pending = crate::runtime_installer::pending_path(&app)?;
            if let Some(parent) = pending.parent() {
                tokio::fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
            }
            tokio::fs::write(pending, "setup").await.map_err(|e| e.to_string())?;
            return Err("Restart your computer and reopen AgenticOS. Setup will continue automatically.".into());
        }
        let ready = tauri::async_runtime::spawn_blocking(crate::docker_runtime::ensure_running)
            .await
            .map_err(|e| e.to_string())?;
        if ready.is_ok() {
            let pending = crate::runtime_installer::pending_path(&app)?;
            if pending.is_file() {
                tokio::fs::remove_file(pending).await.map_err(|e| e.to_string())?;
            }
        }
        return ready;
    }
    let artifact = crate::runtime_installer::selected()?;
    tauri::async_runtime::spawn_blocking(crate::runtime_installer::check_platform)
        .await
        .map_err(|e| e.to_string())??;
    let pending = crate::runtime_installer::pending_path(&app)?;
    if let Some(parent) = pending.parent() {
        tokio::fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
    }
    let disk_path = pending
        .parent()
        .ok_or("The local runtime has no data directory.")?
        .to_path_buf();
    tauri::async_runtime::spawn_blocking(move || crate::local_preflight::disk(&disk_path))
        .await
        .map_err(|e| e.to_string())??;
    tokio::fs::write(&pending, "setup").await.map_err(|e| e.to_string())?;
    let result = prepare(&app, &artifact).await;
    match result {
        #[cfg(not(target_os = "macos"))]
        Ok(crate::runtime_installer::Outcome::RestartRequired) => {
            Err("Restart your computer and reopen AgenticOS. Setup will continue automatically.".into())
        }
        Ok(crate::runtime_installer::Outcome::Installed) => {
            let ready = tauri::async_runtime::spawn_blocking(crate::docker_runtime::ensure_running)
                .await
                .map_err(|e| e.to_string())?;
            if ready.is_ok() {
                tokio::fs::remove_file(pending).await.map_err(|e| e.to_string())?;
            }
            ready
        }
        Err(error) => {
            let _ = tokio::fs::remove_file(pending).await;
            Err(error)
        }
    }
}

async fn prepare(
    app: &AppHandle,
    artifact: &crate::runtime_installer::Installer,
) -> Result<crate::runtime_installer::Outcome, String> {
    #[cfg(target_os = "windows")]
    if crate::runtime_installer::ensure_windows_features().await? == crate::runtime_installer::Outcome::RestartRequired
    {
        return Ok(crate::runtime_installer::Outcome::RestartRequired);
    }
    let dir = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("installers");
    tokio::fs::create_dir_all(&dir).await.map_err(|e| e.to_string())?;
    let destination = dir.join(artifact.filename);
    let cached = tokio::fs::try_exists(&destination).await.map_err(|e| e.to_string())?
        && checksum(&destination).await? == artifact.checksum;
    if !cached {
        let part = destination.with_extension("part");
        let result = download(app, artifact, &part).await;
        if let Err(error) = result {
            let _ = tokio::fs::remove_file(&part).await;
            return Err(error);
        }
        if checksum(&part).await? != artifact.checksum {
            let _ = tokio::fs::remove_file(part).await;
            return Err("The runtime installer failed its integrity check. Retry to download it again.".into());
        }
        tokio::fs::rename(part, &destination).await.map_err(|e| e.to_string())?;
    }
    app.emit_to(
        crate::WINDOW,
        "docker:download",
        serde_json::json!({"message":"Installing local runtime… Approve any system installation prompts."}),
    )
    .map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    {
        debug_assert_eq!(artifact.kind, crate::runtime_installer::Kind::Mac);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_secs();
        let mut quarantine = tokio::process::Command::new("/usr/bin/xattr");
        quarantine
            .args(["-w", "com.apple.quarantine", &format!("0081;{stamp:x};AgenticOS;")])
            .arg(&destination);
        system_command(quarantine, "apply installer safety checks").await?;
        install_macos(app, &destination).await?;
        Ok(crate::runtime_installer::Outcome::Installed)
    }
    #[cfg(not(target_os = "macos"))]
    crate::runtime_installer::install_other(artifact, &destination).await
}

async fn download(app: &AppHandle, artifact: &crate::runtime_installer::Installer, part: &Path) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(1800))
        .connect_timeout(std::time::Duration::from_secs(20))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if allowed_redirect(attempt.url(), attempt.previous().len()) {
                attempt.follow()
            } else {
                attempt.error("The runtime installer redirected outside its official host")
            }
        }))
        .build()
        .map_err(|e| e.to_string())?;
    let mut response = client
        .get(artifact.url)
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|e| format!("Cannot download the local runtime: {e}"))?;
    let mut file = tokio::fs::File::create(part).await.map_err(|e| e.to_string())?;
    let total = response.content_length();
    let mut received = 0;
    let mut updated = std::time::Instant::now();
    while let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? {
        received += chunk.len() as u64;
        if received > 5 * 1024 * 1024 * 1024 {
            return Err("The runtime installer exceeded its download limit.".into());
        }
        file.write_all(&chunk).await.map_err(|e| e.to_string())?;
        if updated.elapsed() > std::time::Duration::from_millis(250) {
            app.emit_to(
                crate::WINDOW,
                "docker:download",
                serde_json::json!({"received":received,"total":total}),
            )
            .map_err(|e| e.to_string())?;
            updated = std::time::Instant::now();
        }
    }
    completed(received, total)?;
    file.flush().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn open_docker(_app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(crate::docker_runtime::ensure_running)
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
    #[tokio::test]
    async fn an_apple_signed_program_is_not_a_docker_installer() {
        assert!(
            system_command(verify_signer(Path::new("/usr/bin/true")), "verify Docker signature")
                .await
                .is_err()
        );
    }
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
fn verify_signer(bundle: &Path) -> tokio::process::Command {
    let mut command = tokio::process::Command::new("/usr/bin/codesign");
    command
        .args(["--verify", "--deep", "--strict", "--test-requirement", "=anchor apple generic and identifier \"com.docker.docker\" and certificate leaf[subject.OU] = \"9BNSXJN65R\""])
        .arg(bundle);
    command
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
        system_command(verify_signer(&bundle), "verify Docker Inc's installer signature").await?;
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
