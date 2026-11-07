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
//! one needs the folder's **full access** grant and remembered native consent
//! for this agent, folder, adapter version and connection.
//! What the agent does inside is gated by its own permission requests, which
//! the server shows as approvals in the chat.

use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
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

/// Several named sessions at once - two projects on one harness, or both
/// harnesses side by side - each one an adapter process of its own.
const MAX_SESSIONS: usize = 8;
static CONFIRMING: Mutex<()> = Mutex::const_new(());
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
    resume_key: Option<ResumeKey>,
    opening_call: Option<String>,
    workspace_root: Option<std::path::PathBuf>,
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
        // The adapter must use the same managed CLI that supplied its options.
        .env_remove("CLAUDE_CODE_EXECUTABLE")
        .env_remove("CODEX_PATH")
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
        let mut lines = BufReader::new(stdout);
        // A line is buffered only up to the limit: an adapter that never ends one
        // would otherwise grow this buffer until the app is killed.
        loop {
            let mut buffer = Vec::new();
            let read = (&mut lines)
                .take(MAX_LINE as u64 + 1)
                .read_until(b'\n', &mut buffer)
                .await;
            if read.map_or(true, |bytes| bytes == 0) {
                break;
            }
            if buffer.last() == Some(&b'\n') {
                buffer.pop();
            }
            if buffer.len() > MAX_LINE {
                break;
            }
            if let Ok(line) = String::from_utf8(buffer) {
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
        resume_key: None,
        opening_call: None,
        workspace_root: None,
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
    #[serde(default)]
    resume_key: Option<String>,
    #[serde(default)]
    fresh_session: bool,
}

/// Opaque scope derived by the server from the tenant, person, agent, conversation
/// and access policy. The native folder and connection revision prevent reuse
/// after changing computers, folders, accounts or deployments.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct ResumeKey {
    scope: String,
    root: String,
    connection: String,
    agent: AgentId,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Remembered {
    key: ResumeKey,
    session_id: String,
}

pub fn remember(history: &mut Vec<Remembered>, key: ResumeKey, session_id: String) {
    history.retain(|item| item.key != key);
    history.push(Remembered { key, session_id });
    if history.len() > 128 {
        history.drain(..history.len() - 128);
    }
}

#[derive(Deserialize)]
struct SessionArgs {
    id: String,
}

/// Native approval is separate from the folder grant: adapters run unsandboxed.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct Consent {
    root: String,
    connection: String,
    agent: AgentId,
    adapter: String,
}

impl Consent {
    fn new(root: &Path, connection: &str, agent: AgentId) -> Self {
        Self {
            root: root.to_string_lossy().into_owned(),
            connection: connection.to_owned(),
            agent,
            adapter: package(agent).to_owned(),
        }
    }
    pub fn is_for_folder(&self, root: &str) -> bool {
        Path::new(&self.root).starts_with(Path::new(root))
    }
}

async fn confirm(app: &AppHandle, agent: AgentId, root: &Path) -> bool {
    let name = crate::local_agents::name(agent);
    let (answered, answer) = oneshot::channel();
    app.dialog()
        .message(format!(
            "{name} starts in {} and runs as your account, without an operating-system sandbox. \
             It can reach other files and the network as your account can. AgenticOS applies \
             the task's read-only or editing policy to the agent's tools. \
             Remember this permission for this agent and folder on the current connection. \
             Remove the folder in Settings to revoke it. Tool approvals and macOS permissions still apply.",
            root.display()
        ))
        .title(format!("Let {name} work on this computer?"))
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Allow for this folder".into(),
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

/// The directory of `program`, put first on `PATH`, so child tools find the
/// private `node` even when the app was started
/// from Finder and inherited no shell `PATH`.
fn path_with(program: &Path) -> Option<String> {
    let dir = program.parent()?;
    let existing = std::env::var_os("PATH").unwrap_or_default();
    std::env::join_paths(std::iter::once(dir.to_path_buf()).chain(std::env::split_paths(&existing)))
        .ok()
        .and_then(|joined| joined.into_string().ok())
}

/// The folder a coding agent may start in: one granted full access, or any folder
/// whole-computer consent covers - the conversation's, or the agent's own.
fn authorized_root(app: &AppHandle, args: &Map<String, Value>, root: &str) -> Result<PathBuf, Refusal> {
    if args.contains_key("computer_grant") {
        crate::computer_access::check(app, args).map_err(|error| Refusal::new("denied", error))?;
        return Ok(PathBuf::from(root));
    }
    local_work::granted_folder_within(app, root, Mode::FullAccess)
}

async fn open(app: &AppHandle, args: &Map<String, Value>, call_id: &str) -> Result<Map<String, Value>, Refusal> {
    let OpenArgs {
        agent,
        root,
        resume_key,
        fresh_session,
    } = serde_json::from_value(Value::Object(args.clone())).map_err(bad)?;
    // The adapter runs as the person, so only a folder granted full access, or
    // whole-computer consent, may host it.
    let root = authorized_root(app, args, &root)?;
    let sessions = app.state::<Sessions>();
    let slot = sessions.reserve().await?;
    let confirmation = CONFIRMING.lock().await;
    let before = crate::settings::current(app);
    let consent = Consent::new(&root, &before.connection_revision, agent);
    if !before.coding_consents.contains(&consent) {
        if !confirm(app, agent, &root).await {
            return Err(Refusal::new("denied", "You did not allow the agent to start."));
        }
        authorized_root(app, args, &root.to_string_lossy())?;
        crate::settings::update(app, |settings| {
            if settings.connection_revision != consent.connection {
                return false;
            }
            if !settings.coding_consents.contains(&consent) {
                settings.coding_consents.push(consent.clone());
            }
            true
        })
        .map_err(|error| Refusal::new("io", error))?
        .1
        .then_some(())
        .ok_or_else(|| Refusal::new("denied", "The connection changed. Start the agent again."))?;
    }
    drop(confirmation);
    let runtime = crate::coding_runtime::prepare(app)
        .await
        .map_err(|error| Refusal::new("io", error))?;
    let settings = crate::settings::current(app);
    let key = resume_key
        .filter(|key| key.len() == 64 && key.bytes().all(|b| b.is_ascii_hexdigit()))
        .map(|scope| ResumeKey {
            scope,
            root: root.to_string_lossy().into_owned(),
            connection: settings.connection_revision.clone(),
            agent,
        });
    let resumed = if fresh_session {
        None
    } else {
        key.as_ref().and_then(|key| {
            settings
                .coding_sessions
                .iter()
                .find(|item| &item.key == key)
                .map(|item| item.session_id.clone())
        })
    };
    if crate::settings::current(app).connection_revision != before.connection_revision {
        return Err(Refusal::new("denied", "The connection changed. Start the agent again."));
    }
    // The person can revoke or narrow the grant while the launch dialog is open.
    authorized_root(app, args, &root.to_string_lossy())?;
    let mut session = spawn(
        &runtime.node,
        &[runtime.adapter(agent).to_string_lossy().into_owned()],
        &runtime.directory,
        path_with(&runtime.node),
    )?;
    session.workspace_root = Some(root);
    session.resume_key = key;
    session.opening_call = Some(call_id.to_owned());
    let id = uuid::Uuid::new_v4().simple().to_string();
    sessions.map.lock().await.insert(id.clone(), session);
    drop(slot);
    Ok(object(serde_json::json!({ "id": id, "session_id": resumed })))
}

async fn remember_running(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let id = args.get("id").and_then(Value::as_str).unwrap_or_default();
    let session_id = args
        .get("session_id")
        .and_then(Value::as_str)
        .filter(|id| {
            !id.is_empty() && id.len() <= 128 && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        })
        .ok_or_else(|| Refusal::new("denied", "That session identifier is not valid."))?;
    let sessions = app.state::<Sessions>();
    let map = sessions.map.lock().await;
    let session = map
        .get(id)
        .ok_or_else(|| Refusal::new("not_found", "That agent is not running."))?;
    if let Some(key) = &session.resume_key {
        crate::settings::update(app, |settings| {
            remember(&mut settings.coding_sessions, key.clone(), session_id.to_owned())
        })
        .map_err(|e| Refusal::new("io", e))?;
    }
    Ok(Map::new())
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

/// A cancelled open can have completed before its reply was observed by the server.
/// Called after aborting and joining that call, so it cannot insert another session.
pub async fn cancel_call(app: &AppHandle, call_id: &str) {
    let sessions = app.state::<Sessions>();
    remove_opened_by(&mut *sessions.map.lock().await, call_id);
}

fn remove_opened_by(map: &mut HashMap<String, Session>, call_id: &str) {
    map.retain(|_, session| {
        if session.opening_call.as_deref() != Some(call_id) {
            return true;
        }
        if let Some(kill) = session.kill.take() {
            let _ = kill.send(());
        }
        false
    });
}

/// Folder revocation ends agents that are already running there.
pub async fn close_for_folder(app: &AppHandle, root: &str) {
    let sessions = app.state::<Sessions>();
    remove_for_folder(&mut *sessions.map.lock().await, Path::new(root));
}

/// Stop the agents working in `root` or in a folder inside it: a session may
/// have started in one project of a granted folder.
fn remove_for_folder(map: &mut HashMap<String, Session>, root: &Path) {
    map.retain(|_, session| {
        if !session
            .workspace_root
            .as_deref()
            .is_some_and(|folder| folder.starts_with(root))
        {
            return true;
        }
        if let Some(kill) = session.kill.take() {
            let _ = kill.send(());
        }
        false
    });
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
pub async fn run(
    app: &AppHandle,
    op: &str,
    args: &Map<String, Value>,
    call_id: &str,
) -> Result<Map<String, Value>, Refusal> {
    match op {
        "agent.open" => open(app, args, call_id).await,
        "agent.send" => send(app, args).await,
        "agent.remember" => remember_running(app, args).await,
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
    async fn a_cancelled_open_reaps_only_the_session_it_created() {
        let mut cancelled = shell("sleep 60");
        cancelled.opening_call = Some("cancelled-call".into());
        let output = Arc::clone(&cancelled.output);
        let mut other = shell("sleep 60");
        other.opening_call = Some("other-call".into());
        let mut map = HashMap::from([("first".into(), cancelled), ("second".into(), other)]);
        remove_opened_by(&mut map, "cancelled-call");
        assert!(!map.contains_key("first"));
        assert!(map.contains_key("second"));
        remove_opened_by(&mut map, "cancelled-call");
        assert_eq!(map.len(), 1);
        let answer = poll_output(&output, 0, Duration::from_secs(5)).await.unwrap();
        assert!(!answer["exit"].is_null());
        remove_opened_by(&mut map, "other-call");
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

    #[tokio::test]
    async fn revoking_one_folder_stops_only_its_agents() {
        let mut removed = shell("sleep 60");
        removed.workspace_root = Some("/revoked".into());
        let stopped = Arc::clone(&removed.output);
        let mut retained = shell("sleep 60");
        retained.workspace_root = Some("/revoked-not".into());
        let mut inside = shell("sleep 60");
        inside.workspace_root = Some("/revoked/app".into());
        let mut sessions = HashMap::from([
            ("removed".into(), removed),
            ("retained".into(), retained),
            ("inside".into(), inside),
        ]);
        remove_for_folder(&mut sessions, Path::new("/revoked"));
        assert!(!sessions.contains_key("removed"));
        assert!(!sessions.contains_key("inside"));
        assert!(sessions.contains_key("retained"));
        let (_, _, exit) = drain(&stopped, 0).await;
        assert!(exit.is_some());
        sessions
            .get_mut("retained")
            .unwrap()
            .kill
            .take()
            .unwrap()
            .send(())
            .unwrap();
    }

    #[test]
    fn remembered_permission_is_scoped_and_survives_serialization() {
        let consent = Consent::new(Path::new("/work"), "account-1", AgentId::ClaudeCode);
        let restored: Consent = serde_json::from_str(&serde_json::to_string(&consent).unwrap()).unwrap();
        assert_eq!(consent, restored);
        for other in [
            Consent::new(Path::new("/other"), "account-1", AgentId::ClaudeCode),
            Consent::new(Path::new("/work"), "account-2", AgentId::ClaudeCode),
            Consent::new(Path::new("/work"), "account-1", AgentId::Codex),
            Consent {
                adapter: "changed-version".into(),
                ..consent.clone()
            },
        ] {
            assert_ne!(consent, other);
        }
        assert!(consent.is_for_folder("/work"));
        let child = Consent::new(Path::new("/work/app"), "https://console.test", AgentId::Codex);
        assert!(child.is_for_folder("/work"));
        assert!(!child.is_for_folder("/worker"));
        assert!(!consent.is_for_folder("/other"));
    }

    #[test]
    fn the_adapters_are_pinned_to_an_exact_version() {
        for agent in [AgentId::ClaudeCode, AgentId::Codex] {
            let name = package(agent);
            let (package, version) = name.rsplit_once('@').expect("a version");
            let manifest: Value = serde_json::from_str(include_str!("../../runtime/package.json")).unwrap();
            assert_eq!(manifest["dependencies"][package], version);
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
    #[test]
    fn continuation_is_bounded_and_isolated_by_folder_connection_and_harness() {
        let key = ResumeKey {
            scope: "a".repeat(64),
            root: "/work".into(),
            connection: "account-1".into(),
            agent: AgentId::ClaudeCode,
        };
        let mut history = Vec::new();
        remember(&mut history, key.clone(), "first".into());
        remember(&mut history, key.clone(), "second".into());
        assert_eq!(history.len(), 1);
        assert_eq!(history[0].session_id, "second");
        for other in [
            ResumeKey {
                root: "/other".into(),
                ..key.clone()
            },
            ResumeKey {
                connection: "account-2".into(),
                ..key.clone()
            },
            ResumeKey {
                agent: AgentId::Codex,
                ..key.clone()
            },
        ] {
            assert_ne!(key, other);
            remember(&mut history, other, "separate".into());
        }
        assert_eq!(history.len(), 4);
        for index in 0..150 {
            remember(
                &mut history,
                ResumeKey {
                    scope: format!("{index:064x}"),
                    ..key.clone()
                },
                "bounded".into(),
            );
        }
        assert_eq!(history.len(), 128);
        let saved = serde_json::to_string(&history).unwrap();
        assert_eq!(serde_json::from_str::<Vec<Remembered>>(&saved).unwrap().len(), 128);
    }
}
