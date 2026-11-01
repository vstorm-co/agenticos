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
//!   that restricts user files to that folder, with read access to system runtimes.
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
#[derive(Debug)]
pub struct Refusal {
    pub kind: &'static str,
    pub message: String,
}

impl Refusal {
    pub(crate) fn new(kind: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
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
        std::env::split_paths(&paths)
            .map(|dir| dir.join(program))
            .find(|candidate| candidate.is_file())
    })
}

fn validate_mode(mode: Mode) -> Result<(), String> {
    if mode == Mode::WorkspaceWrite && !modes().contains(&"workspace_write") {
        return Err("This computer cannot sandbox commands. Choose read only or full access.".into());
    }
    Ok(())
}

/// The granted folders, and the modes this computer can offer for a new one.
#[derive(Serialize)]
pub struct LocalState {
    grants: Vec<Grant>,
    modes: Vec<&'static str>,
}

#[tauri::command]
pub fn local_grants(app: AppHandle) -> LocalState {
    LocalState {
        grants: settings::current(&app).local_grants,
        modes: modes(),
    }
}

/// Pick a folder in the native picker and allow agents to work there, up to `mode`.
#[tauri::command]
pub async fn local_pick_folder(app: AppHandle, mode: Mode) -> Result<Option<Grant>, String> {
    validate_mode(mode)?;
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
    let grant = Grant {
        path: canonical.to_string_lossy().into_owned(),
        mode,
    };
    let stored = grant.clone();
    settings::update(&app, move |settings| {
        settings.local_grants.retain(|existing| existing.path != stored.path);
        settings.local_grants.push(stored);
    })?;
    Ok(Some(grant))
}

/// The most entries the chat's file panel is shown for one folder.
const LISTED: usize = 500;

/// Folders the panel does not walk into: build output and history, not work.
const SKIPPED: [&str; 6] = [".git", "node_modules", "target", ".venv", "__pycache__", ".next"];

/// One file or folder in a granted folder, as the chat's file panel lists it.
#[derive(Serialize)]
pub struct LocalFile {
    path: String,
    size: Option<u64>,
    is_dir: bool,
    /// Seconds since the epoch.
    modified: Option<u64>,
}

fn granted_root(app: &AppHandle, root: &str) -> Result<PathBuf, String> {
    settings::current(app)
        .local_grants
        .into_iter()
        .find(|grant| grant.path == root)
        .map(|grant| PathBuf::from(grant.path))
        .ok_or_else(|| format!("{root} is not a folder you allowed agents to work in."))
}

/// What is in a granted folder, for the chat working there (#2305): paths
/// relative to it, the newest first, at most `LISTED` of them.
#[tauri::command]
pub async fn local_files(app: AppHandle, root: String) -> Result<Vec<LocalFile>, String> {
    let root = granted_root(&app, &root)?;
    tauri::async_runtime::spawn_blocking(move || list_files(&root))
        .await
        .map_err(|e| e.to_string())?
}

fn list_files(root: &Path) -> Result<Vec<LocalFile>, String> {
    let mut found = Vec::new();
    let directory = crate::local_fs::open(root).map_err(|e| e.to_string())?;
    let mut pending = vec![PathBuf::from(".")];
    // Bound traversal as well as the response: a generated tree must not hold
    // the blocking pool or let a symlink take the panel outside its grant.
    'walk: while let Some(dir) = pending.pop() {
        let entries = directory
            .read_dir(&dir)
            .map_err(|e| format!("{}: {e}", dir.display()))?;
        for entry in entries {
            let entry = entry.map_err(|e| e.to_string())?;
            let kind = entry.file_type().map_err(|e| e.to_string())?;
            if kind.is_symlink() || (!kind.is_dir() && !kind.is_file()) {
                continue;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            if kind.is_dir() && SKIPPED.contains(&name.as_str()) {
                continue;
            }
            let path = dir.join(entry.file_name());
            let metadata = directory.symlink_metadata(&path).map_err(|e| e.to_string())?;
            let relative = path.strip_prefix(".").unwrap_or(&path);
            let modified = metadata.modified().ok().map(|time| time.into_std());
            found.push((
                modified,
                LocalFile {
                    path: relative
                        .components()
                        .map(|part| part.as_os_str().to_string_lossy())
                        .collect::<Vec<_>>()
                        .join("/"),
                    size: (!kind.is_dir()).then_some(metadata.len()),
                    is_dir: kind.is_dir(),
                    modified: modified
                        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
                        .map(|since| since.as_secs()),
                },
            ));
            if found.len() >= LISTED * 4 {
                break 'walk;
            }
            if kind.is_dir() {
                pending.push(path);
            }
        }
    }
    found.sort_by_key(|entry| std::cmp::Reverse(entry.0));
    Ok(found.into_iter().take(LISTED).map(|(_, file)| file).collect())
}

/// Keep the native bridge below the device protocol's 16 MiB frame bound.
const FILE_LIMIT: u64 = 10 * 1024 * 1024;

async fn read_file(root: &Path, path: &str) -> Result<Vec<u8>, String> {
    let root = root.to_path_buf();
    let path = path.to_owned();
    tauri::async_runtime::spawn_blocking(move || {
        use std::io::Read;
        let directory = crate::local_fs::open(&root).map_err(|e| e.to_string())?;
        let relative = crate::local_fs::relative(&root, &path).map_err(|e| e.to_string())?;
        let file = crate::local_fs::regular(&directory, &relative, false).map_err(|e| e.to_string())?;
        let mut data = Vec::new();
        file.take(FILE_LIMIT + 1)
            .read_to_end(&mut data)
            .map_err(|e| e.to_string())?;
        if data.len() as u64 > FILE_LIMIT {
            return Err("This file exceeds the 10 MiB local preview limit.".into());
        }
        Ok(data)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// One file in a granted folder, base64, for the chat's file viewer.
#[tauri::command]
pub async fn local_file(app: AppHandle, root: String, path: String) -> Result<String, String> {
    let root = granted_root(&app, &root)?;
    let data = read_file(&root, &path).await?;
    Ok(base64::engine::general_purpose::STANDARD.encode(data))
}

#[tauri::command]
pub fn local_revoke(app: AppHandle, path: String) -> Result<LocalState, String> {
    let (settings, ()) = settings::update(&app, |settings| {
        settings.local_grants.retain(|existing| existing.path != path);
    })?;
    Ok(LocalState {
        grants: settings.local_grants,
        modes: modes(),
    })
}

/// Run one `fs.*` or `shell.run` operation, inside a folder the person granted.
pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let root = text(args, "root")?;
    let asked: Mode = serde_json::from_value(args.get("mode").cloned().unwrap_or(Value::Null))
        .map_err(|_| Refusal::new("denied", "No mode was named."))?;
    if args.contains_key("computer_grant") {
        crate::computer_access::check(app, args).map_err(|error| Refusal::new("denied", error))?;
        let root = PathBuf::from(&root);
        return match op {
            "shell.run" => shell(app, &root, asked, args, true).await,
            _ => files_unrestricted(op, &root, asked, args).await,
        };
    }
    let root = granted_folder(app, &root, asked)?;
    match op {
        "shell.run" => shell(app, &root, asked, args, false).await,
        _ => files(op, &root, asked, args).await,
    }
}

/// A folder the person allowed agents to work in, if the grant reaches `asked`.
pub(crate) fn granted_folder(app: &AppHandle, root: &str, asked: Mode) -> Result<PathBuf, Refusal> {
    let grant = settings::current(app)
        .local_grants
        .into_iter()
        .find(|grant| grant.path == root)
        .ok_or_else(|| {
            Refusal::new(
                "denied",
                format!("{root} is not a folder you allowed agents to work in."),
            )
        })?;
    if asked > grant.mode {
        return Err(Refusal::new(
            "denied",
            format!("You allowed less than that in {root}. Running an agent needs full access."),
        ));
    }
    Ok(PathBuf::from(grant.path))
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
    let joined = if Path::new(path).is_absolute() {
        PathBuf::from(path)
    } else {
        root.join(path)
    };
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
            (Some(parent), Some(name)) => std::fs::canonicalize(parent)
                .map(|p| p.join(name))
                .unwrap_or(normal.clone()),
            _ => normal.clone(),
        },
    };
    if resolved.starts_with(root) {
        Ok(resolved)
    } else {
        Err(Refusal::new(
            "denied",
            format!("{path} is outside the folder you allowed."),
        ))
    }
}

fn writable(mode: Mode) -> Result<(), Refusal> {
    if mode == Mode::ReadOnly {
        Err(Refusal::new("read_only", "This folder is read only for agents."))
    } else {
        Ok(())
    }
}

fn entry(path: &Path, metadata: &cap_std::fs::Metadata) -> Value {
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

async fn files_unrestricted(
    op: &str,
    root: &Path,
    mode: Mode,
    args: &Map<String, Value>,
) -> Result<Map<String, Value>, Refusal> {
    let requested = PathBuf::from(text(args, "path")?);
    let absolute = if requested.is_absolute() {
        requested
    } else {
        root.join(requested)
    };
    // Use the path's own volume as the boundary, including other drives on Windows.
    let boundary = absolute
        .ancestors()
        .last()
        .ok_or_else(|| Refusal::new("denied", "No filesystem root."))?;
    let absolute = inside(boundary, &absolute.to_string_lossy())?;
    let mut args = args.clone();
    args.insert("path".into(), absolute.to_string_lossy().into_owned().into());
    files(op, boundary, mode, &args).await
}

async fn files(op: &str, root: &Path, mode: Mode, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let op = op.to_owned();
    let root = root.to_path_buf();
    let args = args.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let asked = text(&args, "path")?;
        let failed = |error: std::io::Error| io_refusal(&error, &asked);
        let directory = crate::local_fs::open(&root).map_err(failed)?;
        files_at(&directory, &op, &root, mode, &args)
    })
    .await
    .map_err(|error| Refusal::new("io", error.to_string()))?
}

fn files_at(
    directory: &cap_std::fs::Dir,
    op: &str,
    root: &Path,
    mode: Mode,
    args: &Map<String, Value>,
) -> Result<Map<String, Value>, Refusal> {
    let asked = text(args, "path")?;
    let path = crate::local_fs::relative(root, &asked).map_err(|error| io_refusal(&error, &asked))?;
    let failed = |error: std::io::Error| io_refusal(&error, &asked);
    let absolute = if path == Path::new(".") {
        root.to_path_buf()
    } else {
        root.join(&path)
    };
    match op {
        "fs.read" => {
            if directory.metadata(&path).map_err(failed)?.is_dir() {
                return Err(Refusal::new("is_dir", format!("{asked} is a folder")));
            }
            use std::io::Read;
            let mut data = Vec::new();
            crate::local_fs::regular(directory, &path, false)
                .map_err(failed)?
                .take(FILE_LIMIT + 1)
                .read_to_end(&mut data)
                .map_err(failed)?;
            if data.len() as u64 > FILE_LIMIT {
                return Err(Refusal::new(
                    "too_large",
                    "This file exceeds the 10 MiB local read limit.",
                ));
            }
            Ok(object(
                serde_json::json!({ "data": base64::engine::general_purpose::STANDARD.encode(data) }),
            ))
        }
        "fs.write" => {
            writable(mode)?;
            let data = base64::engine::general_purpose::STANDARD
                .decode(text(args, "data")?)
                .map_err(|_| Refusal::new("io", "The file arrived damaged."))?;
            if let Some(parent) = path.parent() {
                directory.create_dir_all(parent).map_err(failed)?;
            }
            use std::io::Write;
            let mut file = crate::local_fs::regular(directory, &path, true).map_err(failed)?;
            file.set_len(0).map_err(failed)?;
            file.write_all(&data).map_err(failed)?;
            Ok(Map::new())
        }
        "fs.stat" => {
            let metadata = directory.metadata(&path).map_err(failed)?;
            Ok(object(entry(&absolute, &metadata)))
        }
        "fs.list" => {
            let mut entries = Vec::new();
            for item in directory.read_dir(&path).map_err(failed)? {
                let item = item.map_err(failed)?;
                if let Ok(metadata) = item.metadata() {
                    entries.push(entry(&absolute.join(item.file_name()), &metadata));
                }
            }
            Ok(object(serde_json::json!({ "entries": entries })))
        }
        "fs.mkdir" => {
            writable(mode)?;
            directory.create_dir_all(&path).map_err(failed)?;
            Ok(Map::new())
        }
        "fs.remove" => {
            writable(mode)?;
            if path == Path::new(".") {
                return Err(Refusal::new("denied", "The folder itself cannot be removed."));
            }
            let metadata = directory.symlink_metadata(&path).map_err(failed)?;
            if metadata.is_dir() {
                directory.remove_dir_all(&path).map_err(failed)?;
            } else {
                directory.remove_file(&path).map_err(failed)?;
            }
            Ok(Map::new())
        }
        "fs.exists" => Ok(object(
            serde_json::json!({ "exists": directory.try_exists(&path).map_err(failed)? }),
        )),
        "fs.realpath" => {
            let resolved = match directory.canonicalize(&path) {
                Ok(path) => root.join(path),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => absolute,
                Err(error) => return Err(failed(error)),
            };
            Ok(object(serde_json::json!({ "path": resolved.to_string_lossy() })))
        }
        other => Err(Refusal::new(
            "denied",
            format!("This app does not do {other} yet. Update AgenticOS."),
        )),
    }
}

async fn shell(
    app: &AppHandle,
    root: &Path,
    mode: Mode,
    args: &Map<String, Value>,
    conversation_consent: bool,
) -> Result<Map<String, Value>, Refusal> {
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
    if mode == Mode::FullAccess && !conversation_consent && !allowed(app, root, &line).await {
        return Err(Refusal::new("denied", "You did not allow that command."));
    }
    let timeout = args.get("timeout").and_then(Value::as_f64).unwrap_or(600.0);
    let mut command = sandboxed(root, mode, &line)?;
    command
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(Value::Object(env)) = args.get("env") {
        for (key, value) in env {
            if let Some(value) = value.as_str() {
                command.env(key, value);
            }
        }
    }
    run_command(command, timeout).await
}

/// Always stop descendants, including when the future is dropped by a lost socket.
pub(crate) struct CommandTree(pub(crate) Box<dyn process_wrap::tokio::ChildWrapper>);

impl Drop for CommandTree {
    fn drop(&mut self) {
        let _ = self.0.start_kill();
    }
}

pub(crate) fn spawn_tree(command: tokio::process::Command) -> Result<CommandTree, Refusal> {
    use process_wrap::tokio::{CommandWrap, KillOnDrop};
    let mut wrapped = CommandWrap::from(command);
    wrapped.wrap(KillOnDrop);
    #[cfg(unix)]
    wrapped.wrap(process_wrap::tokio::ProcessGroup::leader());
    #[cfg(windows)]
    wrapped.wrap(process_wrap::tokio::JobObject);
    wrapped
        .spawn()
        .map(CommandTree)
        .map_err(|e| Refusal::new("io", format!("The command could not start: {e}")))
}

async fn run_command(command: tokio::process::Command, timeout: f64) -> Result<Map<String, Value>, Refusal> {
    let mut child = spawn_tree(command)?;
    let mut stdout = child.0.stdout().take().expect("piped");
    let mut stderr = child.0.stderr().take().expect("piped");
    let collect = async {
        let (out, err) = tokio::join!(capped(&mut stdout), capped(&mut stderr));
        let status = child.0.wait().await;
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
        Err(_) => Err(Refusal::new(
            "timeout",
            format!("The command ran past {timeout:.0} seconds and was stopped."),
        )),
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
            "(version 1)(allow default)(deny file-read*)(deny file-write*)(allow file-read-metadata)\
             (allow file-read* (literal \"/\") (subpath \"{quoted}\") \
             (subpath \"/System\") (subpath \"/usr\") (subpath \"/bin\") (subpath \"/sbin\") \
             (subpath \"/opt/homebrew\") (subpath \"/Library/Apple\") \
             (subpath \"/private/etc\") (subpath \"/private/var/db/dyld\") (subpath \"/dev\"))\
             (allow file-write* (subpath \"{quoted}\") (literal \"/dev/null\") \
             (subpath \"/dev/fd\") (literal \"/dev/stdout\") (literal \"/dev/stderr\") (literal \"/dev/tty\"))"
        );
        let mut command = tokio::process::Command::new("/usr/bin/sandbox-exec");
        command.args(["-p", &profile, "/bin/sh", "-c", line]);
        command
            .env_clear()
            .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin")
            .env("HOME", root)
            .env("TMPDIR", root);
        return Ok(command);
    }
    if cfg!(target_os = "linux") {
        let bwrap = which("bwrap").ok_or_else(|| {
            Refusal::new(
                "denied",
                "Writing in a folder needs bubblewrap on Linux; install it, or use full access.",
            )
        })?;
        let mut command = tokio::process::Command::new(bwrap);
        command.args([
            "--unshare-pid",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--die-with-parent",
        ]);
        // Runtime files only: binding `/` also exposes the person's SSH keys,
        // browser profiles and other files outside the approved workspace.
        for runtime in [
            "/usr",
            "/bin",
            "/sbin",
            "/lib",
            "/lib64",
            "/etc/ld.so.cache",
            "/etc/ld.so.conf",
            "/etc/ld.so.conf.d",
            "/etc/resolv.conf",
            "/etc/hosts",
            "/etc/nsswitch.conf",
            "/etc/ssl/certs",
            "/etc/pki",
        ] {
            if Path::new(runtime).exists() {
                command.args(["--ro-bind", runtime, runtime]);
            }
        }
        command.args([
            "--bind", &root_text, &root_text, "--chdir", &root_text, "--", "/bin/sh", "-c", line,
        ]);
        command
            .env_clear()
            .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin")
            .env("HOME", root)
            .env("TMPDIR", "/tmp");
        return Ok(command);
    }
    Err(Refusal::new(
        "denied",
        "This computer has no sandbox for writing in a folder; use full access.",
    ))
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
    if !part.is_empty()
        && part
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_./=:,@%+".contains(c))
    {
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
    fn process_tree_leaf_fixture() {
        if std::env::var_os("AGENTICOS_TREE_TEST").is_none() {
            return;
        }
        use std::io::Write;
        println!("leaf-ready");
        std::io::stdout().flush().unwrap();
        std::thread::sleep(std::time::Duration::from_secs(60));
    }

    #[test]
    fn process_tree_parent_fixture() {
        if std::env::var_os("AGENTICOS_TREE_TEST").is_none() {
            return;
        }
        let mut leaf = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "local_work::tests::process_tree_leaf_fixture", "--nocapture"])
            .spawn()
            .unwrap();
        leaf.wait().unwrap();
    }

    #[tokio::test]
    async fn cancelling_a_command_stops_its_descendants_and_closes_their_pipes() {
        use tokio::io::{AsyncBufReadExt, BufReader};
        let mut command = tokio::process::Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "local_work::tests::process_tree_parent_fixture",
                "--nocapture",
            ])
            .env("AGENTICOS_TREE_TEST", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        let (send, receive) = tokio::sync::oneshot::channel();
        let task = tokio::spawn(async move {
            let mut tree = spawn_tree(command).unwrap();
            send.send(tree.0.stdout().take().unwrap()).unwrap();
            std::future::pending::<()>().await;
            drop(tree);
        });
        let mut output = BufReader::new(receive.await.unwrap());
        tokio::time::timeout(std::time::Duration::from_secs(10), async {
            loop {
                let mut line = String::new();
                assert_ne!(output.read_line(&mut line).await.unwrap(), 0);
                if line.contains("leaf-ready") {
                    break;
                }
            }
        })
        .await
        .expect("the descendant starts before cancellation");
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        let mut rest = String::new();
        tokio::time::timeout(std::time::Duration::from_secs(5), output.read_to_string(&mut rest))
            .await
            .expect("a surviving descendant would keep stdout open")
            .unwrap();
    }

    #[test]
    fn a_path_is_kept_inside_its_folder() {
        let root = std::env::temp_dir().canonicalize().unwrap();
        assert!(inside(&root, "notes/a.txt").is_ok());
        assert!(inside(&root, &format!("{}/b.txt", root.display())).is_ok());
        assert!(inside(&root, "../../etc/passwd").is_err());
        assert!(inside(&root, "/etc/passwd").is_err());
    }

    fn folder() -> PathBuf {
        let path = std::env::temp_dir().join(format!("agenticos-files-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&path).unwrap();
        path.canonicalize().unwrap()
    }

    #[tokio::test]
    async fn whole_computer_files_can_reach_outside_the_working_directory() {
        let home = folder();
        let elsewhere = folder();
        let destination = elsewhere.join("answer.txt");
        let args = object(serde_json::json!({"path": destination.to_string_lossy(), "data": "ZG9uZQ=="}));
        assert!(files("fs.write", &home, Mode::FullAccess, &args).await.is_err());
        files_unrestricted("fs.write", &home, Mode::FullAccess, &args)
            .await
            .unwrap();
        let answer = files_unrestricted("fs.read", &home, Mode::FullAccess, &args)
            .await
            .unwrap();
        assert_eq!(answer["data"], "ZG9uZQ==");
        std::fs::remove_dir_all(home).unwrap();
        std::fs::remove_dir_all(elsewhere).unwrap();
    }

    #[test]
    fn the_panel_lists_work_and_skips_build_output() {
        let root = folder();
        std::fs::create_dir(root.join("node_modules")).unwrap();
        std::fs::write(root.join("node_modules/ignored.txt"), "hidden").unwrap();
        std::fs::write(root.join("note.txt"), "hello").unwrap();
        let files = list_files(&root).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].path, "note.txt");
        assert_eq!(files[0].size, Some(5));
        assert!(!files[0].is_dir);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn the_panel_does_not_walk_symlinks_or_cycles() {
        let root = folder();
        std::os::unix::fs::symlink(&root, root.join("cycle")).unwrap();
        std::os::unix::fs::symlink("/etc", root.join("outside")).unwrap();
        assert!(list_files(&root).unwrap().is_empty());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn local_reads_are_bounded_and_cannot_leave_the_grant() {
        let root = folder();
        std::fs::write(root.join("note.txt"), "hello").unwrap();
        assert_eq!(read_file(&root, "note.txt").await.unwrap(), b"hello");
        assert!(read_file(&root, "../outside").await.is_err());
        assert!(read_file(&root, ".").await.is_err());
        std::fs::File::create(root.join("huge"))
            .unwrap()
            .set_len(FILE_LIMIT + 1)
            .unwrap();
        assert!(read_file(&root, "huge").await.unwrap_err().contains("limit"));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn device_file_reads_refuse_large_files_without_breaking_following_reads() {
        let root = folder();
        std::fs::File::create(root.join("large"))
            .unwrap()
            .set_len(FILE_LIMIT + 1)
            .unwrap();
        let args = object(serde_json::json!({"path": "large"}));
        let refusal = files("fs.read", &root, Mode::ReadOnly, &args).await.unwrap_err();
        assert_eq!(refusal.kind, "too_large");
        std::fs::write(root.join("small"), "ok").unwrap();
        let args = object(serde_json::json!({"path": "small"}));
        assert_eq!(
            files("fs.read", &root, Mode::ReadOnly, &args).await.unwrap()["data"],
            "b2s="
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[cfg(any(target_os = "macos", target_os = "linux"))]
    #[tokio::test]
    async fn workspace_shell_cannot_read_files_outside_the_grant() {
        let root = folder();
        let outside = folder();
        std::fs::write(root.join("allowed"), "workspace-data").unwrap();
        std::fs::write(outside.join("secret"), "private-data").unwrap();
        let line = format!(
            "cat allowed; cat {}",
            shell_quote(&outside.join("secret").to_string_lossy())
        );
        let output = sandboxed(&root, Mode::WorkspaceWrite, &line)
            .unwrap()
            .current_dir(&root)
            .output()
            .await
            .unwrap();
        let text = String::from_utf8_lossy(&output.stdout);
        assert!(
            text.contains("workspace-data"),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(!text.contains("private-data"));
        assert!(!output.status.success());
        std::fs::remove_dir_all(root).unwrap();
        std::fs::remove_dir_all(outside).unwrap();
    }

    #[test]
    fn grants_require_a_mode_this_computer_can_enforce() {
        assert!(validate_mode(Mode::ReadOnly).is_ok());
        assert!(validate_mode(Mode::FullAccess).is_ok());
        #[cfg(target_os = "windows")]
        assert!(validate_mode(Mode::WorkspaceWrite).is_err());
        #[cfg(target_os = "macos")]
        assert!(validate_mode(Mode::WorkspaceWrite).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn a_replaced_grant_cannot_redirect_an_already_open_operation() {
        let base = folder();
        let root = base.join("approved");
        let outside = base.join("outside");
        std::fs::create_dir(&root).unwrap();
        std::fs::create_dir(&outside).unwrap();
        std::fs::write(outside.join("answer.txt"), "private").unwrap();
        let directory = crate::local_fs::open(&root).unwrap();
        std::fs::rename(&root, base.join("original")).unwrap();
        std::os::unix::fs::symlink(&outside, &root).unwrap();
        let args = object(serde_json::json!({"path":"answer.txt", "data":"ZG9uZQ=="}));
        files_at(&directory, "fs.write", &root, Mode::WorkspaceWrite, &args).unwrap();
        assert_eq!(std::fs::read(outside.join("answer.txt")).unwrap(), b"private");
        assert_eq!(std::fs::read(base.join("original/answer.txt")).unwrap(), b"done");
        assert!(crate::local_fs::open(&root).is_err());
        std::fs::remove_dir_all(base).unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn replaced_child_directories_and_files_cannot_escape_the_grant() {
        let root = folder();
        let outside = folder();
        std::fs::write(outside.join("answer.txt"), "private").unwrap();
        std::fs::create_dir(root.join("child")).unwrap();
        let directory = crate::local_fs::open(&root).unwrap();
        let checked = inside(&root, "child/answer.txt").unwrap();
        std::fs::rename(root.join("child"), root.join("original")).unwrap();
        std::os::unix::fs::symlink(&outside, root.join("child")).unwrap();
        let args = object(serde_json::json!({"path":checked.to_string_lossy(), "data":"ZG9uZQ=="}));
        assert!(files_at(&directory, "fs.write", &root, Mode::WorkspaceWrite, &args).is_err());
        assert!(files_at(&directory, "fs.read", &root, Mode::ReadOnly, &args).is_err());
        assert!(read_file(&root, "child/answer.txt").await.is_err());
        std::os::unix::fs::symlink(outside.join("answer.txt"), root.join("leaf")).unwrap();
        let args = object(serde_json::json!({"path":"leaf", "data":"ZG9uZQ=="}));
        assert!(files_at(&directory, "fs.write", &root, Mode::WorkspaceWrite, &args).is_err());
        files_at(&directory, "fs.remove", &root, Mode::WorkspaceWrite, &args).unwrap();
        assert_eq!(std::fs::read(outside.join("answer.txt")).unwrap(), b"private");
        std::fs::remove_dir_all(root).unwrap();
        std::fs::remove_dir_all(outside).unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn realpath_resolves_internal_links_and_keeps_new_file_paths() {
        let root = folder();
        std::fs::write(root.join("target.txt"), "content").unwrap();
        std::os::unix::fs::symlink("target.txt", root.join("alias")).unwrap();
        let args = object(serde_json::json!({"path":"alias"}));
        let resolved = files("fs.realpath", &root, Mode::ReadOnly, &args).await.unwrap();
        assert_eq!(resolved["path"], root.join("target.txt").to_string_lossy().as_ref());
        let args = object(serde_json::json!({"path":"new.txt"}));
        let resolved = files("fs.realpath", &root, Mode::ReadOnly, &args).await.unwrap();
        assert_eq!(resolved["path"], root.join("new.txt").to_string_lossy().as_ref());
        let args = object(serde_json::json!({"path":"."}));
        let entries = files("fs.list", &root, Mode::ReadOnly, &args).await.unwrap();
        for entry in entries["entries"].as_array().unwrap() {
            assert!(!entry["path"].as_str().unwrap().contains("/./"));
        }
        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn confined_file_operations_preserve_normal_workspace_behaviour() {
        let root = folder();
        let args = object(serde_json::json!({"path":"notes/answer.txt", "data":"ZG9uZQ=="}));
        assert!(files("fs.write", &root, Mode::ReadOnly, &args).await.is_err());
        files("fs.write", &root, Mode::WorkspaceWrite, &args).await.unwrap();
        assert_eq!(
            files("fs.read", &root, Mode::ReadOnly, &args).await.unwrap()["data"],
            "ZG9uZQ=="
        );
        assert_eq!(files("fs.stat", &root, Mode::ReadOnly, &args).await.unwrap()["size"], 4);
        assert_eq!(
            files("fs.exists", &root, Mode::ReadOnly, &args).await.unwrap()["exists"],
            true
        );
        let directory = object(serde_json::json!({"path":"notes"}));
        assert_eq!(
            files("fs.list", &root, Mode::ReadOnly, &directory).await.unwrap()["entries"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        files("fs.remove", &root, Mode::WorkspaceWrite, &directory)
            .await
            .unwrap();
        assert_eq!(
            files("fs.exists", &root, Mode::ReadOnly, &args).await.unwrap()["exists"],
            false
        );
        let root_args = object(serde_json::json!({"path":"."}));
        assert!(files("fs.remove", &root, Mode::WorkspaceWrite, &root_args)
            .await
            .is_err());
        files("fs.mkdir", &root, Mode::WorkspaceWrite, &directory)
            .await
            .unwrap();
        let path = files("fs.realpath", &root, Mode::ReadOnly, &directory).await.unwrap();
        assert_eq!(Path::new(path["path"].as_str().unwrap()), root.join("notes"));
        std::fs::remove_dir_all(root).unwrap();
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
