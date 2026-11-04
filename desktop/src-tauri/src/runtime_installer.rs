//! Tested Docker Desktop release artifacts, independent of host developer tools.
#[cfg(any(test, not(target_os = "macos")))]
use std::path::Path;
use std::path::PathBuf;
#[cfg(not(target_os = "macos"))]
use std::time::Duration;
use tauri::{AppHandle, Manager};

pub struct Installer {
    pub url: &'static str,
    pub filename: &'static str,
    pub checksum: &'static str,
    pub kind: Kind,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Mac,
    Windows,
    Deb,
    Rpm,
}

pub fn artifact(os: &str, arch: &str, distro: &str) -> Result<Installer, String> {
    let (url, filename, checksum, kind) = match (os, arch) {
        ("macos", "aarch64") => ("https://desktop.docker.com/mac/main/arm64/244584/Docker.dmg", "Docker-4.97.0-arm64.dmg", "94e4ccec4a035b7dcdf67cfff0520d4b46ee873ae04b155abc0d22b333cc90ad", Kind::Mac),
        ("macos", "x86_64") => ("https://desktop.docker.com/mac/main/amd64/244584/Docker.dmg", "Docker-4.97.0-amd64.dmg", "98da1a82dac734ba6a14c3e0379f5655ce0bd52a04cf8bb47f4e4642c914f695", Kind::Mac),
        ("windows", "x86_64") => ("https://desktop.docker.com/win/main/amd64/244584/Docker%20Desktop%20Installer.exe", "Docker-4.97.0-amd64.exe", "2668273f82b342a058a28f9ab53ea7bddde10bb6d51307ce2ec54c2d36459744", Kind::Windows),
        ("windows", "aarch64") => ("https://desktop.docker.com/win/main/arm64/244584/Docker%20Desktop%20Installer.exe", "Docker-4.97.0-arm64.exe", "91d18626e6c297bebc9fadb73451844b7cb3300b38161aabba1aa44d87e8c40e", Kind::Windows),
        ("linux", "x86_64") if ["ubuntu", "debian"].contains(&distro) => ("https://desktop.docker.com/linux/main/amd64/244584/docker-desktop-amd64.deb", "Docker-4.97.0-amd64.deb", "ce4008523c495b6b7d19508c671405312c84382b2f7ebb1160d6a1be2189e832", Kind::Deb),
        ("linux", "x86_64") if ["fedora"].contains(&distro) => ("https://desktop.docker.com/linux/main/amd64/244584/docker-desktop-x86_64.rpm", "Docker-4.97.0-amd64.rpm", "7bd6ff6f2778d1213e114e24b1375b843825b00b2e1f8f6eb5914e355160b4ad", Kind::Rpm),
        _ => return Err("Automatic runtime installation is supported on macOS, Windows, and x86-64 Ubuntu, Debian and Fedora. Connect to a company server on this computer, or install a compatible container engine.".into()),
    };
    Ok(Installer {
        url,
        filename,
        checksum,
        kind,
    })
}

pub fn selected() -> Result<Installer, String> {
    let release = std::fs::read_to_string("/etc/os-release").unwrap_or_default();
    let distro = release
        .lines()
        .find_map(|line| line.strip_prefix("ID="))
        .unwrap_or("")
        .trim_matches('"');
    artifact(std::env::consts::OS, std::env::consts::ARCH, distro)
}

pub fn check_platform() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let mut command = std::process::Command::new("/usr/bin/sw_vers");
        command.arg("-productVersion");
        let output = crate::local_stack::run_with_deadline(
            command,
            "check macOS compatibility",
            std::time::Duration::from_secs(10),
        )?;
        let text = String::from_utf8_lossy(&output.stdout);
        let major = text
            .trim()
            .split('.')
            .next()
            .and_then(|value| value.parse::<u32>().ok())
            .ok_or("Could not determine the macOS version.")?;
        if major < 14 {
            return Err(
                "Local installation needs macOS 14 or newer. Update macOS or connect to a company server.".into(),
            );
        }
    }
    #[cfg(target_os = "linux")]
    {
        if !std::path::Path::new("/dev/kvm").exists() {
            return Err("Hardware virtualization is not available on this computer. Enable it with your administrator, or connect to a company server.".into());
        }
    }
    Ok(())
}

pub fn pending_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|dir| dir.join("runtime-setup-pending"))
        .map_err(|e| e.to_string())
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Installed,
    #[cfg(not(target_os = "macos"))]
    RestartRequired,
}

/// Platform authorization is presented by the system; terms stay with Docker.
#[cfg(not(target_os = "macos"))]
pub async fn install_other(installer: &Installer, path: &Path) -> Result<Outcome, String> {
    match installer.kind {
        Kind::Windows => install_windows(path).await,
        Kind::Deb | Kind::Rpm => {
            #[cfg(target_os = "linux")]
            {
                linux_package(installer, path).await
            }
            #[cfg(not(target_os = "linux"))]
            {
                Err("This installer needs a supported Linux desktop.".into())
            }
        }
        Kind::Mac => Err("The macOS installer must use the native installation flow.".into()),
    }
}

#[cfg(any(test, not(target_os = "macos")))]
fn ps_literal(path: &Path) -> String {
    format!("'{}'", path.to_string_lossy().replace('\'', "''"))
}

#[cfg(target_os = "linux")]
fn has_repository(directory: &Path, needle: &str) -> Result<bool, String> {
    let entries = match std::fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(format!("Cannot inspect package sources: {error}")),
    };
    for entry in entries {
        let path = entry.map_err(|e| e.to_string())?.path();
        if !path.is_file() {
            continue;
        }
        let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        if text.contains(needle) {
            return Ok(true);
        }
    }
    Ok(false)
}

#[cfg(target_os = "linux")]
async fn linux_package(installer: &Installer, path: &Path) -> Result<Outcome, String> {
    let staging = path.parent().ok_or("The installer has no cache directory.")?;
    let key = staging.join("docker-repository.asc");
    let source = staging.join("docker-repository.sources");
    let (key_data, source_data, existing, script) = if installer.kind == Kind::Deb {
        let release = std::fs::read_to_string("/etc/os-release").map_err(|e| e.to_string())?;
        let field = |name: &str| {
            release
                .lines()
                .find_map(|line| line.strip_prefix(name))
                .unwrap_or("")
                .trim_matches('"')
        };
        let distro = field("ID=");
        let codename = field("VERSION_CODENAME=");
        if !["ubuntu", "debian"].contains(&distro)
            || codename.is_empty()
            || !codename
                .bytes()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
        {
            return Err("This distribution's package sources are not supported. Connect to a company server or contact your administrator.".into());
        }
        let uri = format!("https://download.docker.com/linux/{distro}");
        let existing = has_repository(Path::new("/etc/apt/sources.list.d"), &uri)?;
        let source = format!("Types: deb\nURIs: {uri}\nSuites: {codename}\nComponents: stable\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/agenticos-docker.asc\n");
        let script = "set -eu; if [ \"$4\" = new ]; then /usr/bin/install -d -m 0755 /etc/apt/keyrings; /usr/bin/install -m 0644 \"$1\" /etc/apt/keyrings/agenticos-docker.asc; /usr/bin/install -m 0644 \"$2\" /etc/apt/sources.list.d/agenticos-docker.sources; fi; /usr/bin/apt-get update; /usr/bin/apt-get install -y \"$3\"";
        (
            include_bytes!("../../runtime/docker-apt.asc").as_slice(),
            source,
            existing,
            script,
        )
    } else {
        let existing = has_repository(
            Path::new("/etc/yum.repos.d"),
            "https://download.docker.com/linux/fedora/",
        )?;
        let source = include_str!("../../runtime/docker-ce.repo").replace(
            "https://download.docker.com/linux/fedora/gpg",
            "file:///etc/pki/rpm-gpg/AGENTICOS-DOCKER",
        );
        let script = "set -eu; if [ \"$4\" = new ]; then /usr/bin/install -d -m 0755 /etc/pki/rpm-gpg; /usr/bin/install -m 0644 \"$1\" /etc/pki/rpm-gpg/AGENTICOS-DOCKER; /usr/bin/install -m 0644 \"$2\" /etc/yum.repos.d/agenticos-docker.repo; fi; /usr/bin/dnf install -y \"$3\"";
        (
            include_bytes!("../../runtime/docker-rpm.asc").as_slice(),
            source,
            existing,
            script,
        )
    };
    tokio::fs::write(&key, key_data).await.map_err(|e| e.to_string())?;
    tokio::fs::write(&source, source_data)
        .await
        .map_err(|e| e.to_string())?;
    let mut command = tokio::process::Command::new("/usr/bin/pkexec");
    command
        .args(["/bin/sh", "-c", script, "agenticos-runtime-install"])
        .arg(&key)
        .arg(&source)
        .arg(path)
        .arg(if existing { "existing" } else { "new" });
    crate::coding_runtime::run(command, "install the local runtime and its dependencies").await?;
    ensure_linux_access().await
}

#[cfg(target_os = "linux")]
pub async fn ensure_linux_access() -> Result<Outcome, String> {
    match std::fs::OpenOptions::new().read(true).write(true).open("/dev/kvm") {
        Ok(_) => return Ok(Outcome::Installed),
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {}
        Err(_) => {
            return Err(
                "Hardware virtualization is not available. Contact your administrator or connect to a company server."
                    .into(),
            )
        }
    }
    let mut identity = std::process::Command::new("/usr/bin/id");
    identity.arg("-un");
    let identity =
        crate::local_stack::run_with_deadline(identity, "identify the desktop user", Duration::from_secs(10))?;
    let name = String::from_utf8(identity.stdout).map_err(|_| "The desktop username was not readable.")?;
    let name = name.trim();
    if name.is_empty() || name == "root" || name.chars().any(char::is_control) {
        return Err("Open AgenticOS under your normal desktop account to prepare virtualization.".into());
    }
    let mut command = tokio::process::Command::new("/usr/bin/pkexec");
    command.args(["/usr/sbin/usermod", "-aG", "kvm", "--", name]);
    crate::coding_runtime::run(command, "authorize local virtualization").await?;
    Ok(Outcome::RestartRequired)
}

#[cfg(target_os = "windows")]
pub async fn ensure_windows_features() -> Result<Outcome, String> {
    use std::process::Stdio;
    let mut probe = tokio::process::Command::new("wsl.exe");
    probe.creation_flags(0x08000000);
    probe
        .arg("--status")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    let status = tokio::time::timeout(Duration::from_secs(20), probe.status())
        .await
        .map_err(|_| "Windows could not check its local runtime features. Restart and retry.")?
        .map_err(|_| {
            "This Windows installation does not provide WSL. Update Windows or connect to a company server."
        })?;
    if status.success() {
        return Ok(Outcome::Installed);
    }
    let mut command = tokio::process::Command::new("powershell.exe");
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    command.args(["-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; $p=Start-Process -FilePath wsl.exe -Verb RunAs -ArgumentList '--install','--no-distribution' -PassThru -Wait; exit $p.ExitCode"]).kill_on_drop(true);
    let installed = tokio::time::timeout(Duration::from_secs(900), command.status())
        .await
        .map_err(|_| "Windows feature preparation took too long. Restart and retry.")?
        .map_err(|e| e.to_string())?;
    if installed.success() || installed.code() == Some(3010) {
        Ok(Outcome::RestartRequired)
    } else {
        Err("Windows could not enable its local runtime features. Approve the system prompt; if virtualization is disabled or restricted by your organization, contact your administrator or connect to a company server.".into())
    }
}

#[cfg(not(target_os = "macos"))]
async fn install_windows(path: &Path) -> Result<Outcome, String> {
    let file = ps_literal(path);
    let script = format!(
        "$ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -LiteralPath {file}; if ($s.Status -ne 'Valid') {{ exit 1 }}; $p=Start-Process -FilePath {file} -ArgumentList 'install','--user' -Wait -PassThru; exit $p.ExitCode"
    );
    let mut command = tokio::process::Command::new("powershell.exe");
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    command
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .kill_on_drop(true);
    let status = tokio::time::timeout(Duration::from_secs(1800), command.status())
        .await
        .map_err(|_| "Runtime installation took too long. Retry setup.")?
        .map_err(|e| e.to_string())?;
    match status.code() {
        Some(0) => Ok(Outcome::Installed),
        Some(3010) => Ok(Outcome::RestartRequired),
        _ => Err("The runtime installer could not finish. Complete any system prompts, then retry. Windows virtualization or WSL may need to be enabled by your administrator.".into()),
    }
}

#[cfg(target_os = "macos")]
fn mac_bundle_complete(bundle: &std::path::Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    ["Contents/Resources/bin/docker", "Contents/MacOS/install"]
        .into_iter()
        .all(|path| {
            bundle
                .join(path)
                .metadata()
                .is_ok_and(|meta| meta.is_file() && meta.len() > 0 && meta.permissions().mode() & 0o111 != 0)
        })
}

pub fn installed() -> bool {
    #[cfg(target_os = "macos")]
    return crate::docker_runtime::desktop_app().is_some_and(|bundle| mac_bundle_complete(&bundle));
    #[cfg(target_os = "windows")]
    return [
        std::env::var_os("LOCALAPPDATA")
            .map(|root| PathBuf::from(root).join("Programs/DockerDesktop/Docker Desktop.exe")),
        std::env::var_os("ProgramFiles").map(|root| PathBuf::from(root).join("Docker/Docker/Docker Desktop.exe")),
    ]
    .into_iter()
    .flatten()
    .any(|path| path.is_file());
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    Path::new("/opt/docker-desktop").is_dir()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(target_os = "macos")]
    #[test]
    fn incomplete_bundles_do_not_prevent_a_repair_installation() {
        use std::os::unix::fs::PermissionsExt;
        let bundle = std::env::temp_dir().join(format!("agenticos-incomplete-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&bundle).unwrap();
        assert!(!mac_bundle_complete(&bundle));
        for name in ["Contents/Resources/bin/docker", "Contents/MacOS/install"] {
            let path = bundle.join(name);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, "binary").unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        assert!(mac_bundle_complete(&bundle));
        std::fs::write(bundle.join("Contents/Resources/bin/docker"), "").unwrap();
        assert!(!mac_bundle_complete(&bundle));
        std::fs::remove_dir_all(bundle).unwrap();
    }
    #[test]
    fn platform_packages_have_exact_versions_and_checksums() {
        for (os, arch, distro, kind) in [
            ("macos", "aarch64", "", Kind::Mac),
            ("macos", "x86_64", "", Kind::Mac),
            ("windows", "x86_64", "", Kind::Windows),
            ("windows", "aarch64", "", Kind::Windows),
            ("linux", "x86_64", "ubuntu", Kind::Deb),
            ("linux", "x86_64", "debian", Kind::Deb),
            ("linux", "x86_64", "fedora", Kind::Rpm),
        ] {
            let artifact = artifact(os, arch, distro).unwrap();
            assert_eq!(artifact.kind, kind);
            assert!(artifact.url.contains("/244584/"));
            assert_eq!(artifact.checksum.len(), 64);
            assert!(artifact.checksum.bytes().all(|c| c.is_ascii_hexdigit()));
        }
        assert!(artifact("linux", "aarch64", "ubuntu").is_err());
        assert!(artifact("linux", "x86_64", "unknown").is_err());
        assert_eq!(
            ps_literal(Path::new("C:/O'Brien/installer.exe")),
            "'C:/O''Brien/installer.exe'"
        );
    }
}
