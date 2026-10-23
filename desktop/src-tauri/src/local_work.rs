//! The person's own agents working in a folder on this computer (#2305).
//!
//! **Only folders the person picked here.** A folder becomes workable through the
//! native folder picker, never through anything the console's page or the server
//! sends: the grant - the folder and the most a run may do in it - lives in this
//! app's settings, and every operation the server asks for names a folder and a
//! mode that are checked against it. A server that asks for another folder, or for
//! more than the person allowed, is refused on this computer.
//!
//! **The modes, as Codex has them.**
//! - Read only: files can be read; nothing is written and no command runs.
//! - Write in the folder: files inside the folder can be written, and commands run
//!   under the operating system's sandbox (Seatbelt on macOS, bubblewrap on Linux)
//!   that lets them write only there and in the temporary directories.
//! - Full access: commands run as the person, unsandboxed - and each one is shown
//!   in a native dialog for the person to allow first.

use std::path::{Component, Path, PathBuf};
use std::process::Stdio;

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::io::AsyncReadExt;

use crate::settings;

/// The most output a command returns, per stream; the rest is cut with a note.
const OUTPUT_LIMIT: usize = 1 << 20;

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    ReadOnly,
    WorkspaceWrite,
    FullAccess,
}

/// A folder the person allowed their agents to work in, and how far.
#[derive(Serialize, Deserialize, Clone, PartialEq, Eq, Debug)]
pub struct Grant {
    pub path: String,
    pub mode: Mode,
}

/// A refusal, with the kind the server turns into the error a tool expects.
pub struct Refusal {
    pub kind: &'static str,
    pub message: String,
}

impl Refusal {
    fn new(kind: &'static str, message: impl Into<String>) -> Self {
        Self { kind, message: message.into() }
    }
}

fn io_refusal(error: &std::io::Error, path: &str) -> Refusal {
    match error.kind() {
        std::io::ErrorKind::NotFound => Refusal::new("not_found", format!("No such file: {path}")),
        std::io::ErrorKind::PermissionDenied => Refusal::new("denied", format!("Not allowed: {path}")),
        std::io::ErrorKind::IsADirectory => Refusal::new("is_dir", format!("{path} is a folder")),
        _ => Refusal::new("io", format!("{path}: {error}")),
    }
}

/// The modes this computer can offer, as it tells the server.
pub fn modes() -> Vec<&'static str> {
    let mut modes = vec!["read_only"];
    if cfg!(target_os = "macos") || (cfg!(target_os = "linux") && which("bwrap").is_some()) {
        modes.push("workspace_write");
    }
    modes.push("full_access");
    modes
}

fn which(program: &str) -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|paths| {
        std::env::split_paths(&paths).map(|dir| dir.join(program)).find(|candidate| candidate.is_file())
    })
}

#[tauri::command]
pub fn local_grants(app: AppHandle) -> Vec<Grant> {
    settings::current(&app).local_grants
}

/// Pick a folder in the native picker and allow agents to work there, up to `mode`.
#[tauri::command]
pub async fn local_pick_folder(app: AppHandle, mode: Mode) -> Result<Option<Grant>, String> {
    let (picked, answer) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_title("Choose the folder your agents may work in")
        .pick_folder(move |folder| {
            let _ = picked.send(folder);
        });
    let Some(folder) = answer.await.ok().flatten() else {
        return Ok(None);
    };
    let path = folder.into_path().map_err(|e| e.to_string())?;
    let canonical = std::fs::canonicalize(&path).map_err(|e| e.to_string())?;
    let grant = Grant { path: canonical.to_string_lossy().into_owned(), mode };
    let stored = grant.clone();
    settings::update(&app, move |settings| {
        settings.local_grants.retain(|existing| existing.path != stored.path);
        settings.local_grants.push(stored);
    })?;
    Ok(Some(grant))
}

#[tauri::command]
pub fn local_revoke(app: AppHandle, path: String) -> Result<Vec<Grant>, String> {
    let (settings, ()) = settings::update(&app, |settings| {
        settings.local_grants.retain(|existing| existing.path != path);
    })?;
    Ok(settings.local_grants)
}

/// Run one `fs.*` or `shell.run` operation, inside a folder the person granted.
pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let root = text(args, "root")?;
    let asked: Mode = serde_json::from_value(args.get("mode").cloned().unwrap_or(Value::Null))
        .map_err(|_| Refusal::new("denied", "No mode was named."))?;
    let grant = settings::current(app)
        .local_grants
        .into_iter()
        .find(|grant| grant.path == root)
        .ok_or_else(|| Refusal::new("denied", format!("{root} is not a folder you allowed agents to work in.")))?;
    if asked > grant.mode {
        return Err(Refusal::new("denied", format!("You allowed less than that in {root}.")));
    }
    let root = PathBuf::from(&grant.path);
    match op {
        "shell.run" => shell(app, &root, asked, args).await,
        _ => files(op, &root, asked, args).await,
    }
}

fn text(args: &Map<String, Value>, key: &str) -> Result<String, Refusal> {
    args.get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| Refusal::new("denied", format!("No {key} was named.")))
}

/// `path` as an absolute path inside `root`, without following `..` out of it.
///
/// The parent of a path that does not exist yet is resolved instead, so a link
/// inside the folder cannot carry a write outside it.
fn inside(root: &Path, path: &str) -> Result<PathBuf, Refusal> {
    let joined = if Path::new(path).is_absolute() { PathBuf::from(path) } else { root.join(path) };
    let mut normal = PathBuf::new();
    for component in joined.components() {
        match component {
            Component::ParentDir => {
                normal.pop();
            }
            Component::CurDir => {}
            other => normal.push(other.as_os_str()),
        }
    }
    let resolved = match std::fs::canonicalize(&normal) {
        Ok(real) => real,
        Err(_) => match (normal.parent(), normal.file_name()) {
            (Some(parent), Some(name)) => std::fs::canonicalize(parent).map(|p| p.join(name)).unwrap_or(normal.clone()),
            _ => normal.clone(),
        },
    };
    if resolved.starts_with(root) {
        Ok(resolved)
    } else {
        Err(Refusal::new("denied", format!("{path} is outside the folder you allowed.")))
    }
}

fn writable(mode: Mode) -> Result<(), Refusal> {
    if mode == Mode::ReadOnly {
        Err(Refusal::new("read_only", "This folder is read only for agents."))
    } else {
        Ok(())
    }
}

fn entry(path: &Path, metadata: &std::fs::Metadata) -> Value {
    serde_json::json!({
        "name": path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default(),
        "path": path.to_string_lossy(),
        "is_dir": metadata.is_dir(),
        "size": if metadata.is_dir() { Value::Null } else { metadata.len().into() },
    })
}

fn object(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

async fn files(op: &str, root: &Path, mode: Mode, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let asked = text(args, "path")?;
    let path = inside(root, &asked)?;
    let failed = |error: std::io::Error| io_refusal(&error, &asked);
    match op {
        "fs.read" => {
            if path.is_dir() {
                return Err(Refusal::new("is_dir", format!("{asked} is a folder")));
            }
            let data = tokio::fs::read(&path).await.map_err(failed)?;
            Ok(object(serde_json::json!({ "data": base64::engine::general_purpose::STANDARD.encode(data) })))
        }
        "fs.write" => {
            writable(mode)?;
            let data = base64::engine::general_purpose::STANDARD
                .decode(text(args, "data")?)
                .map_err(|_| Refusal::new("io", "The file arrived damaged."))?;
            if let Some(parent) = path.parent() {
                tokio::fs::create_dir_all(parent).await.map_err(failed)?;
            }
            tokio::fs::write(&path, data).await.map_err(failed)?;
            Ok(Map::new())
        }
        "fs.stat" => {
            let metadata = tokio::fs::metadata(&path).await.map_err(failed)?;
            Ok(object(entry(&path, &metadata)))
        }
        "fs.list" => {
            let mut reader = tokio::fs::read_dir(&path).await.map_err(failed)?;
            let mut entries = Vec::new();
            while let Some(item) = reader.next_entry().await.map_err(failed)? {
                if let Ok(metadata) = item.metadata().await {
                    entries.push(entry(&item.path(), &metadata));
                }
            }
            Ok(object(serde_json::json!({ "entries": entries })))
        }
        "fs.mkdir" => {
            writable(mode)?;
            tokio::fs::create_dir_all(&path).await.map_err(failed)?;
            Ok(Map::new())
        }
        "fs.remove" => {
            writable(mode)?;
            if path == root {
                return Err(Refusal::new("denied", "The folder itself cannot be removed."));
            }
            let metadata = tokio::fs::symlink_metadata(&path).await.map_err(failed)?;
            if metadata.is_dir() {
                tokio::fs::remove_dir_all(&path).await.map_err(failed)?;
            } else {
                tokio::fs::remove_file(&path).await.map_err(failed)?;
            }
            Ok(Map::new())
        }
        "fs.exists" => Ok(object(serde_json::json!({ "exists": path.exists() }))),
        "fs.realpath" => Ok(object(serde_json::json!({ "path": path.to_string_lossy() }))),
        other => Err(Refusal::new("denied", format!("This app does not do {other} yet. Update AgenticOS."))),
    }
}

async fn shell(app: &AppHandle, root: &Path, mode: Mode, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    if mode == Mode::ReadOnly {
        return Err(Refusal::new("read_only", "Commands do not run in a read-only folder."));
    }
    let line = match args.get("command") {
        Some(Value::String(command)) => command.clone(),
        Some(Value::Array(parts)) => parts
            .iter()
            .filter_map(Value::as_str)
            .map(shell_quote)
            .collect::<Vec<_>>()
            .join(" "),
        _ => return Err(Refusal::new("denied", "No command was named.")),
    };
    if mode == Mode::FullAccess && !allowed(app, root, &line).await {
        return Err(Refusal::new("denied", "You did not allow that command."));
    }
    let timeout = args.get("timeout").and_then(Value::as_f64).unwrap_or(600.0);
    let mut command = sandboxed(root, mode, &line)?;
    command.current_dir(root).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).kill_on_drop(true);
    if let Some(Value::Object(env)) = args.get("env") {
        for (key, value) in env {
            if let Some(value) = value.as_str() {
                command.env(key, value);
            }
        }
    }
    let mut child = command.spawn().map_err(|e| Refusal::new("io", format!("The command could not start: {e}")))?;
    let mut stdout = child.stdout.take().expect("piped");
    let mut stderr = child.stderr.take().expect("piped");
    let collect = async {
        let (out, err) = tokio::join!(capped(&mut stdout), capped(&mut stderr));
        let status = child.wait().await;
        (out, err, status)
    };
    match tokio::time::timeout(std::time::Duration::from_secs_f64(timeout.max(1.0)), collect).await {
        Ok((out, err, status)) => {
            let code = status.ok().and_then(|s| s.code()).unwrap_or(-1);
            Ok(object(serde_json::json!({
                "exit_code": code,
                "stdout": String::from_utf8_lossy(&out),
                "stderr": String::from_utf8_lossy(&err),
            })))
        }
        Err(_) => Err(Refusal::new("timeout", format!("The command ran past {timeout:.0} seconds and was stopped."))),
    }
}

/// A stream's output up to the limit; the rest is read and dropped, so a chatty
/// command is not stalled on a full pipe.
async fn capped(stream: &mut (impl tokio::io::AsyncRead + Unpin)) -> Vec<u8> {
    let mut kept = Vec::new();
    let mut chunk = [0u8; 8192];
    while let Ok(read) = stream.read(&mut chunk).await {
        if read == 0 {
            break;
        }
        let room = OUTPUT_LIMIT.saturating_sub(kept.len());
        kept.extend_from_slice(&chunk[..read.min(room)]);
    }
    if kept.len() >= OUTPUT_LIMIT {
        kept.extend_from_slice(b"\n[output cut at 1 MiB]");
    }
    kept
}

/// The command, wrapped in this OS's sandbox when the mode asks for one.
fn sandboxed(root: &Path, mode: Mode, line: &str) -> Result<tokio::process::Command, Refusal> {
    if mode == Mode::FullAccess {
        return Ok(plain_shell(line));
    }
    let root_text = root.to_string_lossy();
    if cfg!(target_os = "macos") {
        let quoted = root_text.replace('\\', "\\\\").replace('"', "\\\"");
        let profile = format!(
            "(version 1)(allow default)(deny file-write*)\
             (allow file-write* (subpath \"{quoted}\") (subpath \"/private/tmp\") (subpath \"/private/var/folders\") \
             (literal \"/dev/null\") (subpath \"/dev/fd\") (literal \"/dev/stdout\") (literal \"/dev/stderr\") (literal \"/dev/tty\"))"
        );
        let mut command = tokio::process::Command::new("/usr/bin/sandbox-exec");
        command.args(["-p", &profile, "/bin/sh", "-c", line]);
        return Ok(command);
    }
    if cfg!(target_os = "linux") {
        let bwrap = which("bwrap").ok_or_else(|| {
            Refusal::new("denied", "Writing in a folder needs bubblewrap on Linux; install it, or use full access.")
        })?;
        let mut command = tokio::process::Command::new(bwrap);
        command.args(["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--die-with-parent"]);
        command.args(["--bind", &root_text, &root_text, "--chdir", &root_text, "--", "/bin/sh", "-c", line]);
        return Ok(command);
    }
    Err(Refusal::new("denied", "This computer has no sandbox for writing in a folder; use full access."))
}

fn plain_shell(line: &str) -> tokio::process::Command {
    if cfg!(target_os = "windows") {
        let mut command = tokio::process::Command::new("cmd");
        command.args(["/C", line]);
        command
    } else {
        let mut command = tokio::process::Command::new("/bin/sh");
        command.args(["-c", line]);
        command
    }
}

fn shell_quote(part: &str) -> String {
    if !part.is_empty() && part.chars().all(|c| c.is_ascii_alphanumeric() || "-_./=:,@%+".contains(c)) {
        part.to_owned()
    } else {
        format!("'{}'", part.replace('\'', "'\\''"))
    }
}

/// Ask the person, in a native dialog, before a full-access command runs.
async fn allowed(app: &AppHandle, root: &Path, line: &str) -> bool {
    let (answered, answer) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(format!("Your agent wants to run, in {}:\n\n{line}", root.display()))
        .title("Allow this command?")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Run".into(), "Don't run".into()))
        .show(move |allowed| {
            let _ = answered.send(allowed);
        });
    answer.await.unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_path_is_kept_inside_its_folder() {
        let root = std::env::temp_dir().canonicalize().unwrap();
        assert!(inside(&root, "notes/a.txt").is_ok());
        assert!(inside(&root, &format!("{}/b.txt", root.display())).is_ok());
        assert!(inside(&root, "../../etc/passwd").is_err());
        assert!(inside(&root, "/etc/passwd").is_err());
    }

    #[test]
    fn modes_are_ordered_from_least_to_most() {
        assert!(Mode::ReadOnly < Mode::WorkspaceWrite);
        assert!(Mode::WorkspaceWrite < Mode::FullAccess);
    }

    #[test]
    fn argv_is_quoted_into_one_shell_line() {
        assert_eq!(shell_quote("ls"), "ls");
        assert_eq!(shell_quote("a b"), "'a b'");
        assert_eq!(shell_quote("it's"), "'it'\\''s'");
    }
}
