//! Docker processes inherit a complete CLI environment even when launched by Finder.
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const BIN_DIRS: [&str; 5] = [
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/Applications/Docker.app/Contents/Resources/bin",
    "/usr/bin",
    "/opt/docker-desktop/bin",
];

#[cfg(any(windows, test))]
fn windows_bin_dirs(local: Option<&OsStr>, programs: Option<&OsStr>) -> Vec<PathBuf> {
    local
        .map(|root| PathBuf::from(root).join("Programs/DockerDesktop/resources/bin"))
        .into_iter()
        .chain(programs.map(|root| PathBuf::from(root).join("Docker/Docker/resources/bin")))
        .collect()
}

fn paths(inherited: Option<&OsStr>, home: Option<&OsStr>) -> Vec<PathBuf> {
    let mut paths = inherited
        .map(|path| std::env::split_paths(path).collect::<Vec<_>>())
        .unwrap_or_default();
    if let Some(home) = home {
        paths.push(PathBuf::from(home).join(".docker/bin"));
        #[cfg(target_os = "macos")]
        paths.push(PathBuf::from(home).join("Applications/Docker.app/Contents/Resources/bin"));
    }
    paths.extend(BIN_DIRS.iter().map(PathBuf::from));
    #[cfg(windows)]
    paths.extend(windows_bin_dirs(
        std::env::var_os("LOCALAPPDATA").as_deref(),
        std::env::var_os("ProgramFiles").as_deref(),
    ));
    paths
}

pub fn docker() -> Option<PathBuf> {
    paths(std::env::var_os("PATH").as_deref(), std::env::var_os("HOME").as_deref())
        .into_iter()
        .map(|dir| dir.join(if cfg!(windows) { "docker.exe" } else { "docker" }))
        .find(|candidate| candidate.is_file())
}

fn with_paths(docker: &Path, inherited: Option<&OsStr>, home: Option<&OsStr>) -> Result<Command, String> {
    let mut command = Command::new(docker);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut dirs = paths(inherited, home);
    if let Some(parent) = docker.parent() {
        dirs.push(parent.to_path_buf());
    }
    let path = std::env::join_paths(dirs).map_err(|error| format!("Cannot prepare the local runtime PATH: {error}"))?;
    command.env("PATH", path);
    Ok(command)
}

pub fn command(docker: &Path) -> Result<Command, String> {
    with_paths(
        docker,
        std::env::var_os("PATH").as_deref(),
        std::env::var_os("HOME").as_deref(),
    )
}

/// Public product images do not need the person's registry credentials or keychain.
pub fn public_config(dir: &Path) -> Result<PathBuf, String> {
    let root = dir.join("docker-public");
    std::fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    }
    let mut plugins = vec![
        PathBuf::from("/Applications/Docker.app/Contents/Resources/cli-plugins"),
        PathBuf::from("/usr/local/lib/docker/cli-plugins"),
        PathBuf::from("/usr/local/libexec/docker/cli-plugins"),
        PathBuf::from("/opt/homebrew/lib/docker/cli-plugins"),
        PathBuf::from("/usr/lib/docker/cli-plugins"),
        PathBuf::from("/usr/libexec/docker/cli-plugins"),
        PathBuf::from("/opt/docker-desktop/cli-plugins"),
    ];
    if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")) {
        plugins.push(PathBuf::from(&home).join(".docker/cli-plugins"));
        plugins.push(PathBuf::from(home).join("Applications/Docker.app/Contents/Resources/cli-plugins"));
    }
    if let Some(programs) = std::env::var_os("ProgramFiles") {
        plugins.push(PathBuf::from(programs).join("Docker/Docker/resources/cli-plugins"));
    }
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        plugins.push(PathBuf::from(local).join("Programs/DockerDesktop/resources/cli-plugins"));
    }
    if let Some(config) = std::env::var_os("DOCKER_CONFIG") {
        plugins.push(PathBuf::from(config).join("cli-plugins"));
    }
    plugins.retain(|path| path.is_dir());
    // Explicit empty registry entries prevent Docker from auto-detecting an
    // external credential store. These images are public and use anonymous pulls.
    let config = serde_json::json!({"auths": {"ghcr.io": {}, "https://index.docker.io/v1/": {}}, "cliPluginsExtraDirs": plugins});
    let bytes = serde_json::to_vec(&config).map_err(|e| e.to_string())?;
    let temporary = root.join(format!("config-{}.pending", uuid::Uuid::new_v4()));
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    use std::io::Write;
    let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|e| e.to_string())?;
    drop(file);
    std::fs::rename(temporary, root.join("config.json")).map_err(|e| e.to_string())?;
    Ok(root)
}

fn local_endpoint(endpoint: &str) -> Result<String, String> {
    if endpoint.starts_with("unix:///") || endpoint.starts_with("npipe:////./pipe/") {
        Ok(endpoint.to_owned())
    } else {
        Err("The container engine points to another computer. Select a local runtime for installation, or connect to your company server instead.".into())
    }
}

pub fn local_connection(docker: &Path) -> Result<String, String> {
    if std::env::var_os("DOCKER_CONTEXT").is_none() {
        if let Ok(host) = std::env::var("DOCKER_HOST") {
            return local_endpoint(&host);
        }
    }
    let mut inspect = command(docker)?;
    inspect.args(["context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"]);
    let output =
        crate::local_stack::run_with_deadline(inspect, "check the local runtime connection", Duration::from_secs(15))?;
    let host: String = serde_json::from_slice(&output.stdout)
        .map_err(|_| "The local runtime did not provide its connection settings.")?;
    local_endpoint(&host)
}

pub fn ready(docker: &Path) -> Result<bool, String> {
    let endpoint = local_connection(docker)?;
    let mut child = command(docker)?
        .env("DOCKER_HOST", endpoint)
        .env_remove("DOCKER_CONTEXT")
        .args(["info", "--format", "{{.ServerVersion}}"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Cannot check the local runtime: {error}"))?;
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok(status.success()),
            Ok(None) if started.elapsed() < Duration::from_secs(10) => std::thread::sleep(Duration::from_millis(100)),
            result => {
                let _ = child.kill();
                let _ = child.wait();
                return match result {
                    Err(error) => Err(format!("Cannot check the local runtime: {error}")),
                    _ => Ok(false),
                };
            }
        }
    }
}

#[cfg(target_os = "macos")]
pub fn desktop_app() -> Option<PathBuf> {
    std::iter::once(PathBuf::from("/Applications/Docker.app"))
        .chain(std::env::var_os("HOME").map(|home| PathBuf::from(home).join("Applications/Docker.app")))
        .find(|path| path.is_dir())
}

/// Start an installed engine for an explicit local operation, never a status probe.
pub fn ensure_running() -> Result<(), String> {
    let docker = docker().ok_or("Prepare this computer before creating a workspace.")?;
    if ready(&docker)? {
        return Ok(());
    }
    #[cfg(target_os = "macos")]
    let opened = desktop_app()
        .ok_or("The local runtime needs installation. Choose Set up this computer.")
        .and_then(|path| {
            Command::new("/usr/bin/open")
                .args(["-g", "-a"])
                .arg(path)
                .status()
                .map_err(|_| "Cannot open the local runtime.")
        });
    #[cfg(target_os = "windows")]
    let opened = [
        std::env::var_os("LOCALAPPDATA")
            .map(|root| PathBuf::from(root).join("Programs/DockerDesktop/Docker Desktop.exe")),
        std::env::var_os("ProgramFiles").map(|root| PathBuf::from(root).join("Docker/Docker/Docker Desktop.exe")),
    ]
    .into_iter()
    .flatten()
    .find(|path| path.is_file())
    .ok_or("Cannot locate the local runtime.")
    .and_then(|path| {
        Command::new(path)
            .spawn()
            .map(|_| ())
            .map_err(|_| "Cannot start the local runtime.")
    });
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let opened = Command::new("systemctl")
        .args(["--user", "start", "docker-desktop"])
        .status()
        .map_err(|_| "Cannot start the local runtime. Check whether systemd user services are available.");
    {
        #[cfg(not(target_os = "windows"))]
        if !opened.map_err(str::to_owned)?.success() {
            return Err("The local runtime could not open. Retry preparing this computer.".into());
        }
        #[cfg(target_os = "windows")]
        opened.map_err(str::to_owned)?;
        let started = Instant::now();
        while started.elapsed() < Duration::from_secs(180) {
            if ready(&docker)? {
                return Ok(());
            }
            std::thread::sleep(Duration::from_secs(2));
        }
        Err(
            "The local runtime is still starting. Complete any system or Docker Desktop setup prompts, then retry."
                .into(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_installation_is_discoverable_before_the_path_is_refreshed() {
        let local = Path::new("local app data");
        let programs = Path::new("program files");
        assert_eq!(
            windows_bin_dirs(Some(local.as_os_str()), Some(programs.as_os_str())),
            vec![
                local.join("Programs/DockerDesktop/resources/bin"),
                programs.join("Docker/Docker/resources/bin"),
            ]
        );
        assert!(windows_bin_dirs(None, None).is_empty());
    }

    #[cfg(unix)]
    #[test]
    #[ignore = "Requires an installed Docker CLI and the public release registry"]
    fn public_release_metadata_does_not_open_the_keychain() {
        use std::os::unix::fs::PermissionsExt;
        let root = std::env::temp_dir().join(format!("agenticos-public-pull-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let config = public_config(&root).unwrap();
        let helpers = root.join("helpers");
        std::fs::create_dir(&helpers).unwrap();
        for name in ["desktop", "osxkeychain", "pass", "secretservice"] {
            let helper = helpers.join(format!("docker-credential-{name}"));
            std::fs::write(&helper, "#!/bin/sh\n: > \"$AGENTICOS_HELPER_SENTINEL\"\nexit 1\n").unwrap();
            std::fs::set_permissions(helper, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let inherited = std::env::var_os("PATH").unwrap_or_default();
        let path = std::env::join_paths(std::iter::once(helpers).chain(std::env::split_paths(&inherited))).unwrap();
        let mut command = command(&docker().expect("Docker CLI is installed")).unwrap();
        command
            .arg("--config")
            .arg(config)
            .args([
                "manifest",
                "inspect",
                &format!(
                    "ghcr.io/vstorm-co/agenticos-backend:{}",
                    env!("AGENTICOS_PLATFORM_VERSION")
                ),
            ])
            .env("PATH", path)
            .env_remove("DOCKER_AUTH_CONFIG")
            .env("AGENTICOS_HELPER_SENTINEL", root.join("helper-called"));
        let result =
            crate::local_stack::run_with_deadline(command, "inspect public release metadata", Duration::from_secs(60));
        let helper_called = root.join("helper-called").exists();
        std::fs::remove_dir_all(root).unwrap();
        assert!(!helper_called, "Public downloads must not invoke credential helpers");
        assert!(
            result.is_ok(),
            "The public release metadata must be downloadable anonymously"
        );
    }

    #[test]
    fn public_pulls_have_no_credential_helpers_and_do_not_modify_user_config() {
        let root = std::env::temp_dir().join(format!("agenticos-public-docker-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let user = root.join("config.json");
        std::fs::write(&user, r#"{"credsStore":"missing-helper"}"#).unwrap();
        let private = public_config(&root).unwrap();
        let config: serde_json::Value =
            serde_json::from_slice(&std::fs::read(private.join("config.json")).unwrap()).unwrap();
        assert!(config.get("credsStore").is_none());
        assert!(config.get("credHelpers").is_none());
        assert_eq!(config["auths"].as_object().unwrap().len(), 2);
        assert_eq!(
            std::fs::read_to_string(user).unwrap(),
            r#"{"credsStore":"missing-helper"}"#
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn local_installation_refuses_remote_daemons() {
        assert!(local_endpoint("unix:///var/run/docker.sock").is_ok());
        assert!(local_endpoint("npipe:////./pipe/docker_engine").is_ok());
        for endpoint in ["ssh://production", "tcp://example.com:2376", "https://example.com", ""] {
            assert!(local_endpoint(endpoint).is_err());
        }
    }

    #[test]
    fn subprocess_environment_keeps_the_inherited_search_path() {
        let inherited = std::env::join_paths([std::env::temp_dir()]).unwrap();
        let command = with_paths(Path::new("docker"), Some(&inherited), None).unwrap();
        let path = command.get_envs().find(|(name, _)| *name == "PATH").unwrap().1.unwrap();
        assert_eq!(std::env::split_paths(path).next(), Some(std::env::temp_dir()));
    }

    #[cfg(unix)]
    #[test]
    fn readiness_distinguishes_a_stopped_engine_from_a_missing_cli() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("agenticos-ready-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let docker = dir.join("docker");
        assert!(ready(&docker).is_err());
        for (code, expected) in [(0, true), (1, false)] {
            std::fs::write(
                &docker,
                format!(
                    "#!/bin/sh\nif [ \"$1\" = context ]; then printf '\"unix:///test.sock\"'; exit 0; fi\nexit {code}"
                ),
            )
            .unwrap();
            std::fs::set_permissions(&docker, std::fs::Permissions::from_mode(0o700)).unwrap();
            assert_eq!(ready(&docker).unwrap(), expected);
        }
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn finder_children_can_find_docker_helpers_without_changing_docker_config() {
        let command = with_paths(
            Path::new("/custom/bin/docker"),
            Some(OsStr::new("/usr/bin:/bin")),
            Some(OsStr::new("/Users/test user")),
        )
        .unwrap();
        let path = command.get_envs().find(|(name, _)| *name == "PATH").unwrap().1.unwrap();
        let dirs: Vec<_> = std::env::split_paths(path).collect();
        assert_eq!(&dirs[..2], &[PathBuf::from("/usr/bin"), PathBuf::from("/bin")]);
        for expected in [
            "/Users/test user/.docker/bin",
            "/Applications/Docker.app/Contents/Resources/bin",
            "/custom/bin",
        ] {
            assert!(dirs.contains(&PathBuf::from(expected)));
        }
        assert!(!command.get_envs().any(|(name, _)| name == "DOCKER_CONFIG"));
    }

    #[cfg(unix)]
    #[test]
    fn subprocess_resolves_a_sibling_helper_with_a_minimal_gui_path() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("agenticos-helper-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let helper = dir.join("docker-credential-test");
        std::fs::write(&helper, "#!/bin/sh\nprintf helper-found").unwrap();
        std::fs::set_permissions(&helper, std::fs::Permissions::from_mode(0o700)).unwrap();
        let docker = dir.join("docker");
        std::fs::write(&docker, "#!/bin/sh\ndocker-credential-test").unwrap();
        std::fs::set_permissions(&docker, std::fs::Permissions::from_mode(0o700)).unwrap();
        let mut command = with_paths(&docker, Some(OsStr::new("/usr/bin:/bin")), None).unwrap();
        let path: std::ffi::OsString = command
            .get_envs()
            .find(|(name, _)| *name == "PATH")
            .unwrap()
            .1
            .unwrap()
            .to_owned();
        let output = command.env_clear().env("PATH", path).output().unwrap();
        std::fs::remove_dir_all(dir).unwrap();
        assert!(output.status.success());
        assert_eq!(output.stdout, b"helper-found");
    }
}
