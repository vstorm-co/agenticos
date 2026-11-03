//! Docker processes inherit a complete CLI environment even when launched by Finder.
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const BIN_DIRS: [&str; 4] = [
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/Applications/Docker.app/Contents/Resources/bin",
    "/usr/bin",
];

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

pub fn ready(docker: &Path) -> Result<bool, String> {
    let mut child = command(docker)?
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
    return Err("Start your container engine, then retry starting AgenticOS.".into());
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    {
        #[cfg(target_os = "macos")]
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
            std::fs::write(&docker, format!("#!/bin/sh\nexit {code}")).unwrap();
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
