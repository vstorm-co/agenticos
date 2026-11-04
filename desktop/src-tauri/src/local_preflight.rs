//! Refuse a large local install before exhausting storage or an undersized engine.
use std::path::Path;
use std::process::Command;

const MIN_DISK: u64 = 4 * 1024 * 1024 * 1024;
const MIN_MEMORY: u64 = 3 * 1024 * 1024 * 1024;

fn capacity(available: u64, required: u64, resource: &str) -> Result<(), String> {
    if available < required {
        Err(format!("AgenticOS needs at least {} GB of {resource} for local setup. Free up resources or connect to a company server, then retry.", required / 1024 / 1024 / 1024))
    } else {
        Ok(())
    }
}

pub fn disk(path: &Path) -> Result<(), String> {
    #[cfg(unix)]
    let mut command = {
        let mut command = Command::new("/bin/df");
        command.args(["-Pk"]).arg(path);
        command
    };
    #[cfg(windows)]
    let command = {
        let literal = path.to_string_lossy().replace('\'', "''");
        let script =
            format!("[System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot('{literal}')).AvailableFreeSpace");
        let mut command = Command::new("powershell.exe");
        command.args(["-NoProfile", "-NonInteractive", "-Command", &script]);
        command
    };
    #[cfg(unix)]
    command.env("LC_ALL", "C");
    let output = crate::local_stack::run(command, "check available storage")?;
    let text = String::from_utf8_lossy(&output.stdout);
    #[cfg(unix)]
    let available = text
        .lines()
        .last()
        .and_then(|line| line.split_whitespace().nth(3))
        .and_then(|number| number.parse::<u64>().ok())
        .and_then(|value| value.checked_mul(1024));
    #[cfg(windows)]
    let available = text.trim().parse::<u64>().ok();
    capacity(
        available.ok_or("Could not determine available storage. Retry setup.")?,
        MIN_DISK,
        "free storage",
    )
}

pub fn engine(docker: &Path, path: &Path) -> Result<(), String> {
    disk(path)?;
    let mut command = crate::docker_runtime::command(docker)?;
    command.args(["info", "--format", "{{json .MemTotal}}"]);
    let output = crate::local_stack::run(command, "check local memory")?;
    let memory = serde_json::from_slice::<u64>(&output.stdout)
        .map_err(|_| "Could not determine local runtime memory. Retry setup.")?;
    capacity(memory, MIN_MEMORY, "runtime memory")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn resource_limits_refuse_insufficient_capacity_before_downloading() {
        assert!(capacity(MIN_DISK - 1, MIN_DISK, "storage").is_err());
        assert!(capacity(MIN_DISK, MIN_DISK, "storage").is_ok());
        assert!(capacity(0, MIN_MEMORY, "memory").is_err());
    }
}
