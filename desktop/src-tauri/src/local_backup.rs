//! Quiesced local snapshots before a platform update changes the database.
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use crate::local_instances::Instance;

fn version(value: &str) -> Result<(u32, u32, u32), String> {
    let mut parts = value.split('.');
    let mut next = || {
        parts
            .next()
            .filter(|part| !part.is_empty() && part.bytes().all(|c| c.is_ascii_digit()))
            .and_then(|part| part.parse::<u32>().ok())
            .ok_or("The platform release version is invalid.".to_string())
    };
    let parsed = (next()?, next()?, next()?);
    if parsed.0 != 1 || parts.next().is_some() {
        return Err("The platform release version is invalid.".into());
    }
    Ok(parsed)
}

pub fn prevent_downgrade(current: &str, target: &str) -> Result<(), String> {
    if version(current)? > version(target)? {
        return Err("This workspace uses a newer platform release. Update the AgenticOS app before updating this workspace; its database was not changed.".into());
    }
    Ok(())
}

pub fn current_version(docker: &Path, dir: &Path, instance: &Instance) -> Result<String, String> {
    let environment = fs::read_to_string(dir.join(".env")).map_err(|e| e.to_string())?;
    if let Some(pin) = environment
        .lines()
        .find_map(|line| line.strip_prefix("AGENTICOS_VERSION="))
    {
        let pin = pin.trim().trim_matches(['\'', '"']);
        if version(pin).is_ok() {
            return Ok(pin.to_owned());
        }
    }
    // Legacy installs used latest. Read only their cached image's package metadata;
    // do not pull another image or run migrations to discover a version.
    let mut inspect = crate::local_stack::compose(docker, dir, instance)?;
    inspect.args([
        "run",
        "--rm",
        "--no-deps",
        "--pull",
        "never",
        "-T",
        "--entrypoint",
        "python",
        "app",
        "-c",
        "from app import __version__; print(__version__)",
    ]);
    let output = crate::local_stack::run(inspect, "check the existing platform version")?;
    let value = String::from_utf8(output.stdout).map_err(|_| "The platform version was not readable.")?;
    let value = value.trim();
    version(value)?;
    Ok(value.to_owned())
}

pub fn with_version(environment: &str, target: &str) -> Result<String, String> {
    version(target)?;
    let mut value = format!("AGENTICOS_VERSION={target}\n");
    for line in environment
        .lines()
        .filter(|line| !line.trim_start().starts_with("AGENTICOS_VERSION="))
    {
        value.push_str(line);
        value.push('\n');
    }
    Ok(value)
}

pub fn set_version(dir: &Path, version: &str) -> Result<(), String> {
    let environment = fs::read_to_string(dir.join(".env")).map_err(|e| e.to_string())?;
    let contents = with_version(&environment, version)?;
    let temporary = dir.join(format!(".env-version-{}.pending", uuid::Uuid::new_v4()));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    use std::io::Write;
    let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
    if let Err(error) = file.write_all(contents.as_bytes()).and_then(|()| file.sync_all()) {
        drop(file);
        let _ = fs::remove_file(temporary);
        return Err(error.to_string());
    }
    drop(file);
    fs::rename(temporary, dir.join(".env")).map_err(|e| e.to_string())
}

/// Files can be restored here because no migration has started yet.
pub fn apply_configuration(dir: &Path, backup: &Path, version: &str) -> Result<(), String> {
    let applied = set_version(dir, version).and_then(|()| {
        fs::rename(dir.join("docker-compose.update.yml"), dir.join("docker-compose.yml")).map_err(|e| e.to_string())
    });
    if let Err(error) = applied {
        for filename in [".env", "docker-compose.yml"] {
            fs::copy(backup.join(filename), dir.join(filename))
                .map_err(|restore| format!("{error}. Could not restore the previous configuration: {restore}"))?;
        }
        return Err(error);
    }
    Ok(())
}

pub fn snapshot(docker: &Path, dir: &Path, instance: &Instance) -> Result<PathBuf, String> {
    let backup = dir.join("backups").join(uuid::Uuid::new_v4().to_string());
    fs::create_dir_all(&backup).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&backup, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    }
    let result = (|| {
        for filename in [".env", "docker-compose.yml", "docker-compose.desktop.yml"] {
            fs::copy(dir.join(filename), backup.join(filename)).map_err(|e| e.to_string())?;
        }
        let mut database = crate::local_stack::compose(docker, dir, instance)?;
        database.args([
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            "exec pg_dump -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" --format=custom",
        ]);
        write_archive(database, &backup.join("database.dump"))?;
        let mut media = crate::local_stack::compose(docker, dir, instance)?;
        media.args([
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "tar",
            "app",
            "-czf",
            "-",
            "-C",
            "/app/media",
            ".",
        ]);
        write_archive(media, &backup.join("media.tar.gz"))?;
        fs::write(backup.join("complete"), "database, media and deployment keys\n").map_err(|e| e.to_string())?;
        Ok::<_, String>(backup.clone())
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&backup);
    }
    result
}

fn write_archive(mut command: std::process::Command, destination: &Path) -> Result<(), String> {
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(destination).map_err(|e| e.to_string())?;
    command
        .stdin(Stdio::null())
        .stdout(Stdio::from(file))
        .stderr(Stdio::piped());
    tauri::async_runtime::block_on(async {
        let mut child = crate::local_work::spawn_tree(tokio::process::Command::from(command)).map_err(|e| e.message)?;
        let stderr = child.0.stderr().take().ok_or("No backup diagnostics were provided.")?;
        let finished = async {
            let (status, diagnostics) = tokio::join!(child.0.wait(), crate::local_stack::collect_output(stderr, None));
            diagnostics.map_err(|e| e.to_string())?;
            if status.map_err(|e| e.to_string())?.success() {
                Ok(())
            } else {
                Err("Could not back up the local workspace. The update was not applied.".to_string())
            }
        };
        match tokio::time::timeout(Duration::from_secs(1800), finished).await {
            Ok(result) => result,
            Err(_) => {
                let _ = child.0.start_kill();
                let _ = child.0.wait().await;
                Err("The workspace backup took too long. The update was not applied.".into())
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn version_changes_preserve_keys_and_remove_old_duplicate_pins() {
        let original =
            "SECRET_KEY=private\nAGENTICOS_VERSION=latest\nVAULT_MASTER_KEY=private-vault\nAGENTICOS_VERSION=1.1.1\n";
        let updated = with_version(original, "1.38.3").unwrap();
        assert_eq!(updated.matches("AGENTICOS_VERSION=").count(), 1);
        assert!(updated.contains("SECRET_KEY=private\n"));
        assert!(updated.contains("VAULT_MASTER_KEY=private-vault\n"));
        for invalid in ["latest", "2.0.0", "1.2.3\nBAD=1", "1.2"] {
            assert!(with_version(original, invalid).is_err());
        }
    }
    #[test]
    fn database_downgrades_are_refused_before_any_update() {
        assert!(prevent_downgrade("1.40.0", "1.38.3").is_err());
        assert!(prevent_downgrade("1.38.3", "1.40.0").is_ok());
        assert!(prevent_downgrade("1.38.3", "1.38.3").is_ok());
        assert!(prevent_downgrade("latest", "1.38.3").is_err());
    }

    #[test]
    fn configuration_failure_restores_the_previous_pin_before_any_migration() {
        let dir = std::env::temp_dir().join(format!("agenticos-version-test-{}", uuid::Uuid::new_v4()));
        let backup = dir.join("backup");
        fs::create_dir_all(&backup).unwrap();
        for path in [&dir, &backup] {
            fs::write(path.join(".env"), "AGENTICOS_VERSION=1.1.0\nSECRET_KEY=private\n").unwrap();
            fs::write(path.join("docker-compose.yml"), "previous manifest").unwrap();
        }
        assert!(apply_configuration(&dir, &backup, "1.2.0").is_err());
        assert!(fs::read_to_string(dir.join(".env"))
            .unwrap()
            .contains("AGENTICOS_VERSION=1.1.0"));
        fs::write(dir.join("docker-compose.update.yml"), "new manifest").unwrap();
        apply_configuration(&dir, &backup, "1.2.0").unwrap();
        assert!(fs::read_to_string(dir.join(".env"))
            .unwrap()
            .contains("AGENTICOS_VERSION=1.2.0"));
        assert_eq!(
            fs::read_to_string(dir.join("docker-compose.yml")).unwrap(),
            "new manifest"
        );
        fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn archive_streams_are_not_truncated_and_failures_are_explicit() {
        let dir = std::env::temp_dir().join(format!("agenticos-backup-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&dir).unwrap();
        let mut command = std::process::Command::new("/bin/sh");
        command.args(["-c", "head -c 100000 /dev/zero"]);
        write_archive(command, &dir.join("data")).unwrap();
        assert_eq!(fs::metadata(dir.join("data")).unwrap().len(), 100000);
        let command = std::process::Command::new("/usr/bin/false");
        assert!(write_archive(command, &dir.join("failed")).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}
