//! A coding agent started on this computer, as a pipe the server talks ACP
//! through (#2576).
//!
//! The server holds the protocol. This module starts the agent's ACP adapter in
//! a folder the person allowed, hands bytes to its stdin, and returns what it
//! wrote to stdout since the caller last asked. It never reads the protocol, so
//! one change in ACP changes the server, not every installed app.
//!
//! The adapter runs as the person: an agent has to reach its own configuration
//! and the network, which an OS sandbox for a folder would refuse. So starting
//! one needs the folder's **full access** grant, a native confirmation on every
//! start, and nothing else in this module widens what the folder grant says.
//! What the agent does inside is gated by its own permission requests, which
//! the server shows as approvals in the chat.

use std::collections::{HashMap, VecDeque};
use std::path::Path;
use std::process::Stdio;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use serde::Deserialize;
use serde_json::{Map, Value};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::sync::{oneshot, Mutex, Notify};

use crate::local_agents::AgentId;
use crate::local_work::{self, Mode, Refusal};

/// The adapters, pinned: a program fetched at start must not be whatever is
/// newest. Bump a version here after trying it.
fn package(agent: AgentId) -> &'static str {
    match agent {
        AgentId::ClaudeCode => "@agentclientprotocol/claude-agent-acp@0.99.1",
        AgentId::Codex => "@agentclientprotocol/codex-acp@2.5.0",
    }
}

const MAX_SESSIONS: usize = 4;
/// One ACP message; larger ones are an attack or a bug, not a conversation.
const MAX_LINE: usize = 4 << 20;
/// What a session keeps for a caller that has not polled yet.
const BUFFER_LIMIT: usize = 16 << 20;
/// The stderr tail returned with an exit, which is what explains a failed start.
const STDERR_TAIL: usize = 8 << 10;
const MAX_WAIT_MS: u64 = 25_000;
const POLL_LINES: usize = 256;

/// What an agent has written, by absolute line number, so a cursor survives
/// the oldest lines being dropped.
#[derive(Default)]
struct Lines {
    base: u64,
    items: VecDeque<String>,
    bytes: usize,
    exit: Option<i32>,
    stderr: Vec<u8>,
    overflowed: bool,
}

impl Lines {
    fn push(&mut self, line: String) {
        self.bytes += line.len();
        self.items.push_back(line);
        while self.bytes > BUFFER_LIMIT {
            let Some(dropped) = self.items.pop_front() else { break };
            self.bytes -= dropped.len();
            self.base += 1;
            self.overflowed = true;
        }
    }

    fn end(&self) -> u64 {
        self.base + self.items.len() as u64
    }

    /// Up to `POLL_LINES` lines from `cursor`, and the cursor after them.
    fn since(&self, cursor: u64) -> Result<(Vec<String>, u64), String> {
        if cursor < self.base {
            return Err("The agent wrote more than the app keeps; its output was lost.".into());
        }
        let start = (cursor - self.base) as usize;
        let lines: Vec<String> = self.items.iter().skip(start).take(POLL_LINES).cloned().collect();
        let next = cursor + lines.len() as u64;
        Ok((lines, next))
    }

    fn keep_stderr(&mut self, chunk: &[u8]) {
        self.stderr.extend_from_slice(chunk);
        if self.stderr.len() > STDERR_TAIL {
            let cut = self.stderr.len() - STDERR_TAIL;
            self.stderr.drain(..cut);
        }
    }
}

struct Output {
    lines: StdMutex<Lines>,
    changed: Notify,
}

impl Output {
    fn with<R>(&self, change: impl FnOnce(&mut Lines) -> R) -> R {
        let mut lines = self.lines.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let result = change(&mut lines);
        drop(lines);
        self.changed.notify_waiters();
        result
    }
}

struct Session {
    stdin: Mutex<tokio::process::ChildStdin>,
    output: Arc<Output>,
    kill: Option<oneshot::Sender<()>>,
}

/// Every running agent, by the id the server uses.
#[derive(Default)]
pub struct Sessions {
    map: Mutex<HashMap<String, Session>>,
    /// Starts that passed the limit and are still waiting on the person's confirmation.
    reserved: AtomicUsize,
}

/// A place held for a start, given back when it is dropped - started, refused or failed.
struct Slot<'a>(&'a AtomicUsize);

impl Drop for Slot<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

impl Sessions {
    /// Hold a place for one more agent, counting the starts still being confirmed, so
    /// several chats asking at once cannot all pass a check made before any of them is
    /// inserted.
    async fn reserve(&self) -> Result<Slot<'_>, Refusal> {
        let map = self.map.lock().await;
        if map.len() + self.reserved.load(Ordering::SeqCst) >= MAX_SESSIONS {
            return Err(Refusal::new("denied", "Too many agents are running. Stop one first."));
        }
        self.reserved.fetch_add(1, Ordering::SeqCst);
        Ok(Slot(&self.reserved))
    }
}

/// Start `program` in `cwd` and begin collecting what it writes.
fn spawn(program: &Path, args: &[String], cwd: &Path, path_env: Option<String>) -> Result<Session, Refusal> {
    let mut command = tokio::process::Command::new(program);
    command
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(path_env) = path_env {
        command.env("PATH", path_env);
    }
    let mut child = local_work::spawn_tree(command)?;
    let stdin = child.0.stdin().take().expect("piped");
    let stdout = child.0.stdout().take().expect("piped");
    let mut stderr = child.0.stderr().take().expect("piped");
    let output = Arc::new(Output {
        lines: StdMutex::default(),
        changed: Notify::new(),
    });

    let reader = Arc::clone(&output);
    let read_stdout = tokio::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.len() <= MAX_LINE {
                reader.with(|kept| kept.push(line));
            }
        }
    });
    let errors = Arc::clone(&output);
    let read_stderr = tokio::spawn(async move {
        let mut chunk = [0u8; 4096];
        while let Ok(read) = stderr.read(&mut chunk).await {
            if read == 0 {
                break;
            }
            errors.with(|kept| kept.keep_stderr(&chunk[..read]));
        }
    });

    let (kill, killed) = oneshot::channel();
    let watcher = Arc::clone(&output);
    tokio::spawn(async move {
        let status = tokio::select! {
            status = child.0.wait() => status,
            _ = killed => {
                let _ = child.0.start_kill();
                child.0.wait().await
            }
        };
        // The pipes close with the process; let them drain before reporting the exit.
        let _ = read_stdout.await;
        let _ = read_stderr.await;
        let code = status.ok().and_then(|status| status.code()).unwrap_or(-1);
        watcher.with(|kept| kept.exit = Some(code));
    });
    Ok(Session {
        stdin: Mutex::new(stdin),
        output,
        kill: Some(kill),
    })
}

/// A JSON object, in one line - what one ACP message is.
fn one_message(message: &Value) -> Result<String, Refusal> {
    if !message.is_object() {
        return Err(Refusal::new("denied", "An agent message is a JSON object."));
    }
    let line = serde_json::to_string(message).map_err(|e| Refusal::new("denied", e.to_string()))?;
    if line.len() > MAX_LINE {
        return Err(Refusal::new("denied", "That message is too large for an agent."));
    }
    Ok(line)
}

#[derive(Deserialize)]
struct OpenArgs {
    agent: AgentId,
    root: String,
}

#[derive(Deserialize)]
struct SessionArgs {
    id: String,
}

async fn confirm(app: &AppHandle, agent: AgentId, root: &Path) -> bool {
    let name = crate::local_agents::name(agent);
    let (answered, answer) = oneshot::channel();
    app.dialog()
        .message(format!(
            "{name} will work in {} as you: it can read and change files and run commands there. \
             AgenticOS asks in the chat before it does anything its own permissions gate.",
            root.display()
        ))
        .title(format!("Let {name} work on this computer?"))
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Allow".into(),
            "Don't allow".into(),
        ))
        .show(move |allowed| {
            let _ = answered.send(allowed);
        });
    answer.await.unwrap_or(false)
}

fn bad(error: serde_json::Error) -> Refusal {
    Refusal::new("denied", format!("The request was not understood: {error}"))
}

/// The directory of `program`, put first on `PATH`, so an adapter launched by
/// `npx` finds the `node` installed beside it even when the app was started
/// from Finder and inherited no shell `PATH`.
fn path_with(program: &Path) -> Option<String> {
    let dir = program.parent()?;
    let existing = std::env::var_os("PATH").unwrap_or_default();
    std::env::join_paths(std::iter::once(dir.to_path_buf()).chain(std::env::split_paths(&existing)))
        .ok()
        .and_then(|joined| joined.into_string().ok())
}

async fn open(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let OpenArgs { agent, root } = serde_json::from_value(Value::Object(args.clone())).map_err(bad)?;
    // The adapter runs as the person, so only a folder granted full access may host it.
    let root = local_work::granted_folder(app, &root, Mode::FullAccess)?;
    let sessions = app.state::<Sessions>();
    let slot = sessions.reserve().await?;
    let npx = crate::local_agents::locate("npx").ok_or_else(|| {
        Refusal::new(
            "denied",
            "Node.js is not installed, and the agent adapter needs it. Install Node.js 22 or later.",
        )
    })?;
    if !confirm(app, agent, &root).await {
        return Err(Refusal::new("denied", "You did not allow the agent to start."));
    }
    // npx runs from a folder of the app's own: it reads the `.npmrc` of its working
    // directory, and a repository's `.npmrc` could name a registry that answers the
    // pinned package's name with its own code. The agent still works in `root`, which
    // ACP's `session/new` names.
    let runtime = app
        .path()
        .app_data_dir()
        .map_err(|e| Refusal::new("io", e.to_string()))?
        .join("agent-runtime");
    std::fs::create_dir_all(&runtime).map_err(|e| Refusal::new("io", e.to_string()))?;
    let session = spawn(
        &npx,
        &["--yes".into(), package(agent).into()],
        &runtime,
        path_with(&npx),
    )?;
    let id = uuid::Uuid::new_v4().simple().to_string();
    sessions.map.lock().await.insert(id.clone(), session);
    drop(slot);
    Ok(object(serde_json::json!({ "id": id })))
}

async fn send(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let SessionArgs { id } = serde_json::from_value(Value::Object(args.clone())).map_err(bad)?;
    let line = one_message(args.get("message").unwrap_or(&Value::Null))?;
    let sessions = app.state::<Sessions>();
    let map = sessions.map.lock().await;
    let session = map
        .get(&id)
        .ok_or_else(|| Refusal::new("not_found", "That agent is not running."))?;
    let mut stdin = session.stdin.lock().await;
    stdin
        .write_all(format!("{line}\n").as_bytes())
        .await
        .map_err(|e| Refusal::new("io", format!("The agent is not listening: {e}")))?;
    stdin
        .flush()
        .await
        .map_err(|e| Refusal::new("io", format!("The agent is not listening: {e}")))?;
    Ok(Map::new())
}

/// The new lines after `cursor`, waiting up to `wait_ms` for one.
async fn poll_output(output: &Output, cursor: u64, wait: Duration) -> Result<Map<String, Value>, Refusal> {
    let deadline = tokio::time::Instant::now() + wait;
    loop {
        let changed = output.changed.notified();
        tokio::pin!(changed);
        // Registered before the check, so a line pushed in between is not missed.
        changed.as_mut().enable();
        let (lines, next, exit, stderr) = {
            let kept = output.lines.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            let (lines, next) = kept.since(cursor).map_err(|e| Refusal::new("io", e))?;
            let drained = next >= kept.end();
            let exit = if drained { kept.exit } else { None };
            let stderr = exit.map(|_| String::from_utf8_lossy(&kept.stderr).into_owned());
            (lines, next, exit, stderr)
        };
        if !lines.is_empty() || exit.is_some() || tokio::time::Instant::now() >= deadline {
            return Ok(object(serde_json::json!({
                "lines": lines,
                "cursor": next,
                "exit": exit,
                "stderr": stderr,
            })));
        }
        let _ = tokio::time::timeout_at(deadline, changed).await;
    }
}

async fn poll(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let SessionArgs { id } = serde_json::from_value(Value::Object(args.clone())).map_err(bad)?;
    let cursor = args.get("cursor").and_then(Value::as_u64).unwrap_or(0);
    let wait = args
        .get("wait_ms")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        .min(MAX_WAIT_MS);
    let output = {
        let sessions = app.state::<Sessions>();
        let map = sessions.map.lock().await;
        Arc::clone(
            &map.get(&id)
                .ok_or_else(|| Refusal::new("not_found", "That agent is not running."))?
                .output,
        )
    };
    poll_output(&output, cursor, Duration::from_millis(wait)).await
}

async fn close(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let SessionArgs { id } = serde_json::from_value(Value::Object(args.clone())).map_err(bad)?;
    if let Some(mut session) = app.state::<Sessions>().map.lock().await.remove(&id) {
        if let Some(kill) = session.kill.take() {
            let _ = kill.send(());
        }
    }
    Ok(Map::new())
}

/// Stop every agent: the server is gone, so nothing is listening to them.
pub async fn close_all(app: &AppHandle) {
    let sessions = app.state::<Sessions>();
    let mut map = sessions.map.lock().await;
    for (_, mut session) in map.drain() {
        if let Some(kill) = session.kill.take() {
            let _ = kill.send(());
        }
    }
}

fn object(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

/// Run one `agent.*` operation.
pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    match op {
        "agent.open" => open(app, args).await,
        "agent.send" => send(app, args).await,
        "agent.poll" => poll(app, args).await,
        "agent.close" => close(app, args).await,
        other => Err(Refusal::new("denied", format!("This app does not do {other}."))),
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn shell(script: &str) -> Session {
        let dir = std::env::temp_dir();
        spawn(Path::new("/bin/sh"), &["-c".into(), script.into()], &dir, None).expect("a shell starts")
    }

    async fn drain(output: &Output, cursor: u64) -> (Vec<String>, u64, Option<i64>) {
        let answer = poll_output(output, cursor, Duration::from_secs(5)).await.unwrap();
        let lines = answer["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| l.as_str().unwrap().to_owned())
            .collect();
        (lines, answer["cursor"].as_u64().unwrap(), answer["exit"].as_i64())
    }

    #[tokio::test]
    async fn what_the_agent_writes_comes_back_in_order_with_its_exit() {
        let session = shell("echo '{\"a\":1}'; echo '{\"b\":2}'; echo oops >&2; exit 3");
        let (mut seen, mut cursor, mut exit) = (Vec::new(), 0, None);
        while exit.is_none() {
            let (lines, next, code) = drain(&session.output, cursor).await;
            seen.extend(lines);
            (cursor, exit) = (next, code);
        }
        assert_eq!(seen, vec![r#"{"a":1}"#, r#"{"b":2}"#]);
        assert_eq!(exit, Some(3));
        let answer = poll_output(&session.output, cursor, Duration::ZERO).await.unwrap();
        assert_eq!(answer["stderr"], "oops\n");
    }

    #[tokio::test]
    async fn a_message_sent_reaches_stdin_as_one_line() {
        let session = shell("read line; echo \"got:$line\"");
        {
            let mut stdin = session.stdin.lock().await;
            stdin
                .write_all(format!("{}\n", one_message(&serde_json::json!({"id": 1})).unwrap()).as_bytes())
                .await
                .unwrap();
        }
        let (lines, _, _) = drain(&session.output, 0).await;
        assert_eq!(lines, vec![r#"got:{"id":1}"#]);
    }

    #[tokio::test]
    async fn a_poll_with_nothing_new_returns_empty_after_its_wait() {
        let session = shell("sleep 5");
        let started = std::time::Instant::now();
        let answer = poll_output(&session.output, 0, Duration::from_millis(150))
            .await
            .unwrap();
        assert!(answer["lines"].as_array().unwrap().is_empty());
        assert!(answer["exit"].is_null());
        assert!(started.elapsed() >= Duration::from_millis(140));
    }

    #[tokio::test]
    async fn closing_stops_the_process_and_reports_an_exit() {
        let mut session = shell("sleep 30");
        session.kill.take().unwrap().send(()).unwrap();
        let (_, _, exit) = drain(&session.output, 0).await;
        assert!(exit.is_some());
    }

    #[test]
    fn only_a_json_object_is_one_message() {
        assert!(one_message(&serde_json::json!({"jsonrpc": "2.0"})).is_ok());
        assert!(one_message(&serde_json::json!("text")).is_err());
        assert!(one_message(&serde_json::json!([1])).is_err());
        assert!(one_message(&Value::Null).is_err());
        assert!(!one_message(&serde_json::json!({"a": "line\nbreak"}))
            .unwrap()
            .contains('\n'));
    }

    #[test]
    fn lines_dropped_for_size_are_reported_rather_than_skipped() {
        let mut lines = Lines::default();
        let big = "x".repeat(BUFFER_LIMIT / 2 + 1);
        lines.push(big.clone());
        lines.push(big.clone());
        lines.push(big);
        assert_eq!(lines.base, 2);
        assert!(lines.since(0).is_err());
        assert_eq!(lines.since(2).unwrap().0.len(), 1);
        assert_eq!(lines.end(), 3);
    }

    #[test]
    fn stderr_keeps_only_its_tail() {
        let mut lines = Lines::default();
        lines.keep_stderr(&vec![b'a'; STDERR_TAIL]);
        lines.keep_stderr(b"end");
        assert_eq!(lines.stderr.len(), STDERR_TAIL);
        assert!(lines.stderr.ends_with(b"end"));
    }

    #[tokio::test]
    async fn starts_waiting_on_a_confirmation_count_against_the_limit() {
        let sessions = Sessions::default();
        let mut held = Vec::new();
        for _ in 0..MAX_SESSIONS {
            held.push(sessions.reserve().await.expect("a free place"));
        }
        assert!(sessions.reserve().await.is_err());
        held.pop();
        let again = sessions.reserve().await;
        assert!(again.is_ok());
        assert!(sessions.reserve().await.is_err());
    }

    #[test]
    fn the_adapters_are_pinned_to_an_exact_version() {
        for agent in [AgentId::ClaudeCode, AgentId::Codex] {
            let name = package(agent);
            let version = name.rsplit_once('@').expect("a version").1;
            assert!(
                version.split('.').count() == 3 && version.chars().all(|c| c.is_ascii_digit() || c == '.'),
                "{name}"
            );
        }
    }

    #[test]
    fn path_puts_the_programs_own_directory_first() {
        let joined = path_with(Path::new("/opt/node/bin/npx")).unwrap();
        assert!(joined.starts_with("/opt/node/bin:"));
    }
}
