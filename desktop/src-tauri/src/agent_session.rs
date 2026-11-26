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

pub mod accounts;
mod pi_keys;

use sha2::{Digest, Sha256};
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

use crate::local_work::{self, Mode, Refusal};

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum AgentId {
    ClaudeCode,
    Codex,
    Custom,
}

impl AgentId {
    fn builtin(self) -> Option<crate::local_agents::AgentId> {
        match self {
            Self::ClaudeCode => Some(crate::local_agents::AgentId::ClaudeCode),
            Self::Codex => Some(crate::local_agents::AgentId::Codex),
            Self::Custom => None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
struct ExternalIdentity {
    id: String,
    revision: String,
}

impl From<&crate::external_agents::Registration> for ExternalIdentity {
    fn from(agent: &crate::external_agents::Registration) -> Self {
        Self {
            id: agent.id.clone(),
            revision: agent.revision.clone(),
        }
    }
}

/// The adapters, pinned: a program fetched at start must not be whatever is
/// newest. Bump a version here after trying it.
fn package(agent: AgentId) -> &'static str {
    match agent {
        AgentId::ClaudeCode => "@agentclientprotocol/claude-agent-acp@0.99.1",
        AgentId::Codex => "@agentclientprotocol/codex-acp@2.5.0",
        AgentId::Custom => "custom",
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
    capture_pi_state: bool,
    pi_session_file: Option<String>,
}

impl Lines {
    fn accepts_reference(&self, value: &str) -> bool {
        if self.capture_pi_state {
            self.pi_session_file.as_deref() == Some(value)
        } else {
            !value.is_empty()
                && value.len() <= 128
                && value
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        }
    }

    fn push(&mut self, line: String) {
        if self.capture_pi_state {
            if let Ok(record) = serde_json::from_str::<Value>(&line) {
                if record.get("type").and_then(Value::as_str) == Some("response")
                    && record.get("command").and_then(Value::as_str) == Some("get_state")
                {
                    self.pi_session_file = record
                        .get("success")
                        .and_then(Value::as_bool)
                        .filter(|success| *success)
                        .and_then(|_| record.get("data")?.get("sessionFile")?.as_str())
                        .filter(|path| {
                            !path.is_empty()
                                && path.len() <= 4096
                                && !path.chars().any(char::is_control)
                                && Path::new(path).is_absolute()
                        })
                        .map(str::to_owned);
                }
            }
        }
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
    external_id: Option<String>,
    builtin_id: Option<crate::local_agents::AgentId>,
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

fn muse_key_environment(command: &mut tokio::process::Command, key: Option<&std::ffi::OsStr>) -> Result<(), Refusal> {
    let key = key.and_then(std::ffi::OsStr::to_str).filter(|value| !value.trim().is_empty())
        .ok_or_else(|| Refusal::new("denied", "Muse API-key mode requires META_API_KEY in the Desktop environment. No saved-account fallback was selected."))?;
    command.env("META_API_KEY", key);
    Ok(())
}

fn qwen_subscription_environment(command: &mut tokio::process::Command) {
    for name in ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "DASHSCOPE_API_KEY"] {
        command.env_remove(name);
    }
}

/// A vendor-owned key store scoped to this child, never the person's saved login.
pub(crate) struct KeyModeHome(std::path::PathBuf, bool);
impl Drop for KeyModeHome {
    fn drop(&mut self) {
        if self.1 {
            let _ = std::fs::remove_file(self.0.join("auth.json"));
        } else {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}

fn key_mode_home() -> Result<KeyModeHome, Refusal> {
    let path = std::env::temp_dir().join(format!("agenticos-native-{}", uuid::Uuid::new_v4()));
    let builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    let builder = {
        use std::os::unix::fs::DirBuilderExt;
        let mut builder = builder;
        builder.mode(0o700);
        builder
    };
    builder
        .create(&path)
        .map_err(|_| Refusal::new("denied", "Could not create a private runtime profile."))?;
    Ok(KeyModeHome(path, false))
}

fn private_key_directory(path: &Path) -> Result<(), Refusal> {
    std::fs::create_dir_all(path)
        .map_err(|_| Refusal::new("denied", "Could not create private Grok session storage."))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| Refusal::new("denied", "Could not restrict Grok session storage."))?;
    }
    Ok(())
}

fn kimi_launch(program: &Path) -> Result<(PathBuf, KeyModeHome), Refusal> {
    use std::io::Read;
    #[cfg(windows)]
    if program
        .file_stem()
        .is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("kimi"))
    {
        if let Some(python) = program
            .parent()
            .map(|directory| directory.join("python.exe"))
            .filter(|path| path.is_file())
        {
            let directory = key_mode_home()?;
            std::fs::write(
                directory.0.join("host.py"),
                include_str!("../../runtime/kimi_session.py"),
            )
            .map_err(|_| Refusal::new("denied", "Could not prepare the Kimi session host."))?;
            return Ok((python, directory));
        }
    }
    let mut prefix = Vec::new();
    std::fs::File::open(program)
        .and_then(|file| file.take(4096).read_to_end(&mut prefix))
        .map_err(|_| Refusal::new("denied", "Could not read the registered Kimi launcher."))?;
    let python = std::str::from_utf8(&prefix).ok().and_then(|text| text.lines().next())
        .and_then(|line| line.strip_prefix("#!")).map(str::trim).map(PathBuf::from)
        .filter(|path| path.is_absolute() && path.is_file() && path.file_name().is_some_and(|name| name.to_string_lossy().starts_with("python")))
        .ok_or_else(|| Refusal::new("denied", "Session model selection requires the documented Python-installed Kimi CLI; its launcher must name its interpreter."))?;
    let directory = key_mode_home()?;
    std::fs::write(
        directory.0.join("host.py"),
        include_str!("../../runtime/kimi_session.py"),
    )
    .map_err(|_| Refusal::new("denied", "Could not prepare the Kimi session host."))?;
    Ok((python, directory))
}

pub(crate) fn key_profile(
    command: &mut tokio::process::Command,
    provider: crate::external_agents::Provider,
) -> Result<Option<KeyModeHome>, Refusal> {
    if provider != crate::external_agents::Provider::GrokApiKey {
        return Ok(None);
    }
    let home = key_mode_home()?;
    command.env("GROK_HOME", &home.0);
    Ok(Some(home))
}

fn api_key_environment(
    command: &mut tokio::process::Command,
    provider: crate::external_agents::Provider,
    key: Option<&std::ffi::OsStr>,
) -> Result<(), Refusal> {
    let key = key
        .and_then(std::ffi::OsStr::to_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| {
            Refusal::new(
                "denied",
                "This API-key template requires its key in the Desktop environment. No saved login was selected.",
            )
        })?;
    match provider {
        crate::external_agents::Provider::CursorApiKey => {
            command
                .env_remove("CURSOR_AUTH_TOKEN")
                .env("CURSOR_API_KEY", key)
                .env("NO_OPEN_BROWSER", "1");
        }
        crate::external_agents::Provider::GrokApiKey => {
            command
                .env_remove("GROK_CODE_XAI_API_KEY")
                .env_remove("GROK_AUTH_PROVIDER_COMMAND")
                .env("XAI_API_KEY", key);
        }
        _ => {
            return Err(Refusal::new(
                "denied",
                "This registration does not accept an environment key.",
            ))
        }
    }
    Ok(())
}

fn grok_account_environment(command: &mut tokio::process::Command) {
    command
        .env_remove("XAI_API_KEY")
        .env_remove("GROK_CODE_XAI_API_KEY")
        .env("GROK_DISABLE_API_KEY_AUTH", "true");
}

fn vibe_environment(command: &mut tokio::process::Command) {
    command
        .env("VIBE_ENABLE_TELEMETRY", "false")
        .env("VIBE_EXPERIMENTAL_ENABLE_MODEL_CATALOG", "true");
}

fn cline_environment(
    command: &mut tokio::process::Command,
    api_key_mode: bool,
    key: Option<&std::ffi::OsStr>,
) -> Result<(), Refusal> {
    command.env("CLINE_PROVIDER", "cline");
    if api_key_mode {
        let key = key
            .filter(|value| value.to_str().is_some_and(|text| !text.trim().is_empty()))
            .ok_or_else(|| {
                Refusal::new(
                    "denied",
                    "Start Desktop with CLINE_API_KEY set to use this registration. No saved account was selected.",
                )
            })?;
        command.env("CLINE_API_KEY", key);
    } else {
        command.env_remove("CLINE_API_KEY");
    }
    Ok(())
}

/// Account mode never sees a key; key mode never falls back to the saved Google sign-in.
fn antigravity_environment(
    command: &mut tokio::process::Command,
    api_key_mode: bool,
    key: Option<&std::ffi::OsStr>,
) -> Result<(), Refusal> {
    command
        .env_remove("GEMINI_API_KEY")
        .env_remove("GOOGLE_API_KEY")
        .env_remove("GOOGLE_GENAI_USE_VERTEXAI")
        .env_remove("GOOGLE_GENAI_USE_GCA");
    if api_key_mode {
        let key = key
            .filter(|value| value.to_str().is_some_and(|text| !text.trim().is_empty()))
            .ok_or_else(|| {
                Refusal::new(
                    "denied",
                    "Start Desktop with GEMINI_API_KEY set to use this registration. The saved Google sign-in was not used.",
                )
            })?;
        command.env("GEMINI_API_KEY", key);
    }
    Ok(())
}

/// The credential environment a provider's sessions get; the model catalog uses the same one.
pub(crate) fn provider_environment(
    command: &mut tokio::process::Command,
    provider: crate::external_agents::Provider,
    gemini_key: Option<&GeminiKey>,
) -> Result<(), Refusal> {
    if matches!(
        provider,
        crate::external_agents::Provider::Antigravity | crate::external_agents::Provider::AntigravityApiKey
    ) {
        // A run's selected vault key takes precedence over the key Desktop inherited.
        let key = gemini_key
            .map(|selected| std::ffi::OsString::from(&selected.0))
            .or_else(|| std::env::var_os("GEMINI_API_KEY"));
        antigravity_environment(
            command,
            provider == crate::external_agents::Provider::AntigravityApiKey,
            key.as_deref(),
        )?;
    }
    if matches!(
        provider,
        crate::external_agents::Provider::Cline | crate::external_agents::Provider::ClineApiKey
    ) {
        let key = std::env::var_os("CLINE_API_KEY");
        cline_environment(
            command,
            provider == crate::external_agents::Provider::ClineApiKey,
            key.as_deref(),
        )?;
    }
    if provider == crate::external_agents::Provider::MuseApiKey {
        let key = std::env::var_os("META_API_KEY");
        muse_key_environment(command, key.as_deref())?;
    }
    if provider == crate::external_agents::Provider::QwenSubscription {
        qwen_subscription_environment(command);
    }
    if matches!(
        provider,
        crate::external_agents::Provider::CursorApiKey | crate::external_agents::Provider::GrokApiKey
    ) {
        let variable = if provider == crate::external_agents::Provider::CursorApiKey {
            "CURSOR_API_KEY"
        } else {
            "XAI_API_KEY"
        };
        api_key_environment(command, provider, std::env::var_os(variable).as_deref())?;
    }
    if provider == crate::external_agents::Provider::Grok {
        grok_account_environment(command);
    }
    if provider == crate::external_agents::Provider::MistralVibe {
        vibe_environment(command);
    }
    if provider == crate::external_agents::Provider::Cursor {
        cursor_account_environment(command);
    }
    Ok(())
}

/// Vault credentials for one launch; a template accepts at most one of them.
#[derive(Clone, Copy, Default)]
struct Keys<'a> {
    pi: Option<&'a pi_keys::Prepared>,
    gemini: Option<&'a GeminiKey>,
    model: Option<&'a str>,
    grok_home: Option<&'a Path>,
}

/// A vault Gemini key the server exported for one Antigravity key-template launch.
#[derive(Deserialize)]
#[serde(try_from = "String")]
pub(crate) struct GeminiKey(String);

impl TryFrom<String> for GeminiKey {
    type Error = &'static str;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        if (8..=16384).contains(&value.len()) && value.bytes().all(|byte| (33..=126).contains(&byte)) {
            Ok(Self(value))
        } else {
            Err("a printable API key")
        }
    }
}

impl std::fmt::Debug for GeminiKey {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("GeminiKey([redacted])")
    }
}

/// The ACP login each template enforces before a session; `None` keeps the CLI's own choice.
pub(crate) fn login_method(provider: crate::external_agents::Provider) -> Option<&'static str> {
    match provider {
        crate::external_agents::Provider::Antigravity => Some("oauth-personal"),
        crate::external_agents::Provider::AntigravityApiKey => Some("gemini-api-key"),
        crate::external_agents::Provider::Cursor | crate::external_agents::Provider::CursorApiKey => {
            Some("cursor_login")
        }
        crate::external_agents::Provider::Cline => Some("cline"),
        crate::external_agents::Provider::MistralVibe => Some("browser-auth"),
        crate::external_agents::Provider::Grok => Some("cached_token"),
        crate::external_agents::Provider::GrokApiKey => Some("xai.api_key"),
        crate::external_agents::Provider::Kimi => Some("login"),
        crate::external_agents::Provider::Devin => Some("devin-browser"),
        crate::external_agents::Provider::Muse => Some("muse-cli"),
        crate::external_agents::Provider::MuseApiKey => Some("muse-api-key"),
        _ => None,
    }
}

pub(crate) fn launch_models(provider: crate::external_agents::Provider) -> bool {
    use crate::external_agents::Provider;
    matches!(
        provider,
        Provider::MistralVibe | Provider::Kimi | Provider::QwenSubscription | Provider::Devin
    )
}

fn cursor_account_environment(command: &mut tokio::process::Command) {
    command
        .env_remove("CURSOR_API_KEY")
        .env_remove("CURSOR_AUTH_TOKEN")
        .env("NO_OPEN_BROWSER", "1");
}

/// Start `program` in `cwd` and begin collecting what it writes.
#[cfg(all(test, unix))]
fn spawn(program: &Path, args: &[String], cwd: &Path, path_env: Option<String>) -> Result<Session, Refusal> {
    spawn_authenticated(program, args, cwd, path_env, crate::external_agents::Provider::Custom)
}

fn spawn_authenticated(
    program: &Path,
    args: &[String],
    cwd: &Path,
    path_env: Option<String>,
    provider: crate::external_agents::Provider,
) -> Result<Session, Refusal> {
    spawn_with_pi(program, args, cwd, path_env, provider, None)
}

fn spawn_with_pi(
    program: &Path,
    args: &[String],
    cwd: &Path,
    path_env: Option<String>,
    provider: crate::external_agents::Provider,
    selected: Option<&pi_keys::Prepared>,
) -> Result<Session, Refusal> {
    spawn_with_bridge(
        program,
        args,
        cwd,
        path_env,
        provider,
        Keys {
            pi: selected,
            gemini: None,
            model: None,
            grok_home: None,
        },
        None,
    )
}

fn spawn_with_bridge(
    program: &Path,
    args: &[String],
    cwd: &Path,
    path_env: Option<String>,
    provider: crate::external_agents::Provider,
    keys: Keys<'_>,
    bridge: Option<&crate::coding_runtime::Runtime>,
) -> Result<Session, Refusal> {
    let kimi = if provider == crate::external_agents::Provider::Kimi && keys.model.is_some() {
        Some(kimi_launch(program)?)
    } else {
        None
    };
    let launch_program = kimi.as_ref().map_or(program, |(python, _)| python.as_path());
    let mut launch_args = if let Some((_, script)) = &kimi {
        vec![script.0.join("host.py").to_string_lossy().into_owned()]
    } else {
        args.to_vec()
    };
    if let Some(model) = keys.model {
        if matches!(
            provider,
            crate::external_agents::Provider::Devin | crate::external_agents::Provider::QwenSubscription
        ) {
            launch_args.splice(0..0, ["--model".to_owned(), model.to_owned()]);
        }
    }
    let mut command = if let Some(runtime) = bridge {
        let mut command = tokio::process::Command::new(&runtime.node);
        command
            .arg(runtime.platform_bridge())
            .arg(
                if provider == crate::external_agents::Provider::Pi || pi_keys::key_template(provider) {
                    "pi"
                } else {
                    "acp"
                },
            )
            .arg(launch_program);
        command
    } else {
        tokio::process::Command::new(launch_program)
    };
    command
        .args(launch_args)
        .current_dir(cwd)
        // The adapter must use the same managed CLI that supplied its options.
        .env_remove("CLAUDE_CODE_EXECUTABLE")
        .env_remove("CODEX_PATH")
        .env_remove("AGENTICOS_BRIDGE_URL")
        .env_remove("AGENTICOS_BRIDGE_TOKEN")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    provider_environment(&mut command, provider, keys.gemini)?;
    if let Some(model) = keys.model {
        if provider == crate::external_agents::Provider::MistralVibe {
            command.env("VIBE_ACTIVE_MODEL", model);
        }
        if provider == crate::external_agents::Provider::Kimi {
            command.env_remove("KIMI_MODEL_NAME").env("AGENTICOS_KIMI_MODEL", model);
        }
    }
    if let Some(path_env) = path_env {
        command.env("PATH", path_env);
    }
    if let Some(selected) = keys.pi {
        selected.apply(&mut command);
    }
    let key_profile = if let Some(path) = keys.grok_home {
        private_key_directory(path)?;
        // A crash may have left a CLI-owned key. A new launch always needs the
        // explicit environment key, never yesterday's persisted credential.
        match std::fs::remove_file(path.join("auth.json")) {
            Ok(()) => (),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => {
                return Err(Refusal::new(
                    "denied",
                    "Could not clear the previous Grok key credential.",
                ))
            }
        }
        command.env("GROK_HOME", path);
        Some(KeyModeHome(path.to_path_buf(), true))
    } else {
        key_profile(&mut command, provider)?
    };
    let cleanup = keys.pi.map(|selected| selected.agent_dir.clone());
    let mut child = local_work::spawn_tree(command)?;
    let stdin = child.0.stdin().take().expect("piped");
    let stdout = child.0.stdout().take().expect("piped");
    let mut stderr = child.0.stderr().take().expect("piped");
    let output = Arc::new(Output {
        lines: StdMutex::new(Lines {
            capture_pi_state: provider == crate::external_agents::Provider::Pi || pi_keys::key_template(provider),
            ..Lines::default()
        }),
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
        drop(kimi);
        drop(key_profile);
        if let Some(directory) = cleanup {
            let _ = tokio::fs::remove_dir_all(directory).await;
        }
        watcher.with(|kept| kept.exit = Some(code));
    });
    Ok(Session {
        stdin: Mutex::new(stdin),
        output,
        kill: Some(kill),
        resume_key: None,
        opening_call: None,
        workspace_root: None,
        external_id: None,
        builtin_id: None,
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
    #[serde(default)]
    custom_agent_id: Option<String>,
    #[serde(default)]
    supports_auth_modes: bool,
    #[serde(default)]
    supports_model_constraints: bool,
    #[serde(default)]
    supports_configuration_policy: bool,
    #[serde(default)]
    accepted_protocols: Vec<String>,
    #[serde(default)]
    pi_key: Option<pi_keys::SelectedKey>,
    #[serde(default)]
    gemini_key: Option<GeminiKey>,
    #[serde(default)]
    runtime_model: Option<String>,
    #[serde(default)]
    platform_tools: bool,
    #[serde(default)]
    state_scope: Option<String>,
    root: String,
    mode: Mode,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    external: Option<ExternalIdentity>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Remembered {
    key: ResumeKey,
    session_id: String,
}

impl Remembered {
    pub fn is_for_external(&self, id: &str) -> bool {
        self.key.external.as_ref().is_some_and(|agent| agent.id == id)
    }
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    external: Option<ExternalIdentity>,
    #[serde(default)]
    platform_tools: bool,
}

impl Consent {
    fn new(root: &Path, connection: &str, agent: AgentId) -> Self {
        Self {
            root: root.to_string_lossy().into_owned(),
            connection: connection.to_owned(),
            agent,
            adapter: package(agent).to_owned(),
            external: None,
            platform_tools: false,
        }
    }
    pub fn is_for_external(&self, id: &str) -> bool {
        self.external.as_ref().is_some_and(|agent| agent.id == id)
    }
    pub fn is_for_folder(&self, root: &str) -> bool {
        Path::new(&self.root).starts_with(Path::new(root))
    }
}

async fn confirm(
    app: &AppHandle,
    agent: AgentId,
    root: &Path,
    external: Option<&crate::external_agents::Registration>,
    platform_tools: bool,
) -> bool {
    let name = external
        .map(|item| item.name.as_str())
        .unwrap_or_else(|| agent.builtin().map(crate::local_agents::name).unwrap_or("ACP"));
    let policy = if external.is_some() {
        "This custom program owns its login, tools, model and charges. Read-only confinement is not guaranteed. Remove its registration to revoke access."
    } else {
        "AgenticOS applies the task's read-only or editing policy to the agent's tools."
    };
    let platform = if platform_tools {
        "This also lets the program use this run's AgenticOS platform tools and receive their data. Platform permissions, budgets, approvals and output screening still apply."
    } else {
        ""
    };
    let (answered, answer) = oneshot::channel();
    app.dialog()
        .message(format!(
            "{name} starts in {} and runs as your account, without an operating-system sandbox. \
             It can reach other files and the network as your account can. {policy} {platform} \
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
pub(crate) fn path_with(program: &Path) -> Option<String> {
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
        custom_agent_id,
        supports_auth_modes,
        supports_model_constraints,
        supports_configuration_policy,
        accepted_protocols,
        pi_key,
        gemini_key,
        runtime_model,
        platform_tools,
        state_scope,
        root,
        mode,
        resume_key,
        fresh_session,
    } = serde_json::from_value(Value::Object(args.clone())).map_err(bad)?;
    if mode != Mode::FullAccess {
        return Err(Refusal::new(
            "denied",
            "Native ACP agents require an explicitly selected full-access folder mode.",
        ));
    }
    if runtime_model.as_ref().is_some_and(|model| {
        model.is_empty() || model.len() > 256 || model.starts_with('-') || model.chars().any(char::is_control)
    }) {
        return Err(Refusal::new(
            "denied",
            "Choose a model ID of at most 256 characters without control characters.",
        ));
    }
    // The adapter runs as the person, so only a folder granted full access, or
    // whole-computer consent, may host it.
    let root = authorized_root(app, args, &root)?;
    let sessions = app.state::<Sessions>();
    let slot = sessions.reserve().await?;
    let confirmation = CONFIRMING.lock().await;
    let before = crate::settings::current(app);
    let external = match (agent, custom_agent_id.as_deref()) {
        (AgentId::Custom, Some(id)) => Some(
            before
                .external_agents
                .iter()
                .find(|item| item.id == id)
                .cloned()
                .ok_or_else(|| Refusal::new("denied", "Register this ACP agent in Desktop app settings first."))?,
        ),
        (AgentId::Custom, None) => return Err(Refusal::new("denied", "Name a registered ACP agent.")),
        (_, Some(_)) => {
            return Err(Refusal::new(
                "denied",
                "A built-in agent cannot select a custom registration.",
            ))
        }
        (_, None) => None,
    };
    if external.as_ref().is_some_and(|item| {
        matches!(
            item.provider,
            crate::external_agents::Provider::Antigravity
                | crate::external_agents::Provider::AntigravityApiKey
                | crate::external_agents::Provider::Cursor
                | crate::external_agents::Provider::CursorApiKey
                | crate::external_agents::Provider::Cline
                | crate::external_agents::Provider::MistralVibe
                | crate::external_agents::Provider::Grok
                | crate::external_agents::Provider::GrokApiKey
                | crate::external_agents::Provider::Devin
                | crate::external_agents::Provider::Kimi
                | crate::external_agents::Provider::QwenSubscription
        )
    }) && !supports_auth_modes
    {
        return Err(Refusal::new(
            "denied",
            "Update the AgenticOS server to use this account authentication mode.",
        ));
    }
    if external
        .as_ref()
        .is_some_and(|item| item.provider == crate::external_agents::Provider::OpenCodeGo)
        && !supports_model_constraints
    {
        return Err(Refusal::new(
            "denied",
            "Update the AgenticOS server to use OpenCode Go model constraints.",
        ));
    }
    if external.as_ref().is_some_and(|item| {
        matches!(
            item.provider,
            crate::external_agents::Provider::MistralVibe
                | crate::external_agents::Provider::Kimi
                | crate::external_agents::Provider::QwenSubscription
                | crate::external_agents::Provider::Devin
        )
    }) && !supports_configuration_policy
    {
        return Err(Refusal::new(
            "denied",
            "Update the AgenticOS server to preserve this CLI's model configuration.",
        ));
    }
    let protocol = external.as_ref().map_or("acp", |item| {
        if item.provider == crate::external_agents::Provider::Pi || pi_keys::key_template(item.provider) {
            "pi_rpc"
        } else {
            "acp"
        }
    });
    if protocol != "acp" && !accepted_protocols.iter().any(|accepted| accepted == protocol) {
        return Err(Refusal::new(
            "denied",
            "Update the AgenticOS server to support this runtime protocol.",
        ));
    }
    let mut consent = Consent::new(&root, &before.connection_revision, agent);
    consent.external = external.as_ref().map(ExternalIdentity::from);
    consent.platform_tools = platform_tools;
    if !before.coding_consents.contains(&consent) {
        if !confirm(app, agent, &root, external.as_ref(), platform_tools).await {
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
    let needs_muse = external.as_ref().is_some_and(|item| {
        matches!(
            item.provider,
            crate::external_agents::Provider::Muse | crate::external_agents::Provider::MuseApiKey
        )
    });
    if needs_muse && !supports_auth_modes {
        return Err(Refusal::new(
            "denied",
            "Update the AgenticOS server to use Muse credential reporting.",
        ));
    }
    let key_template = external
        .as_ref()
        .is_some_and(|item| pi_keys::key_template(item.provider));
    if key_template != pi_key.is_some()
        || pi_key
            .as_ref()
            .is_some_and(|selected| !external.as_ref().is_some_and(|item| selected.admits(item.provider)))
    {
        return Err(Refusal::new(
            "denied",
            "A Pi vault-key launch requires the matching native provider template and a selected vault key.",
        ));
    }
    if gemini_key.is_some()
        && !external
            .as_ref()
            .is_some_and(|item| item.provider == crate::external_agents::Provider::AntigravityApiKey)
    {
        return Err(Refusal::new(
            "denied",
            "A Gemini vault key requires the Antigravity Gemini API key template.",
        ));
    }
    let runtime = if agent.builtin().is_some()
        || needs_muse
        || platform_tools
        || external
            .as_ref()
            .is_some_and(|item| item.provider == crate::external_agents::Provider::Hermes)
    {
        Some(
            crate::coding_runtime::prepare(app)
                .await
                .map_err(|error| Refusal::new("io", error))?,
        )
    } else {
        None
    };
    let _changing = crate::external_agents::CHANGING.lock().await;
    if app.state::<accounts::AccountFlows>().is_busy() {
        return Err(Refusal::new(
            "denied",
            "Finish the native account operation before starting another runtime.",
        ));
    }
    let settings = crate::settings::current(app);
    let key = resume_key
        .filter(|key| key.len() == 64 && key.bytes().all(|b| b.is_ascii_hexdigit()))
        .map(|scope| ResumeKey {
            scope,
            root: root.to_string_lossy().into_owned(),
            connection: settings.connection_revision.clone(),
            agent,
            external: external.as_ref().map(ExternalIdentity::from),
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
    let grok_home = if key.is_some()
        && external
            .as_ref()
            .is_some_and(|entry| entry.provider == crate::external_agents::Provider::GrokApiKey)
    {
        use sha2::{Digest, Sha256};
        let identity =
            serde_json::to_vec(&key).map_err(|_| Refusal::new("denied", "Could not scope Grok sessions."))?;
        Some(
            app.path()
                .app_data_dir()
                .map_err(|_| Refusal::new("denied", "Could not open native session storage."))?
                .join("grok-key-runtime")
                .join(format!("{:x}", Sha256::digest(identity))),
        )
    } else {
        None
    };
    let mut session = if let Some(external) = &external {
        if !crate::settings::current(app).external_agents.contains(external) {
            return Err(Refusal::new("denied", "The ACP registration changed. Start again."));
        }

        if external.provider == crate::external_agents::Provider::Hermes {
            let scope = state_scope.as_deref().ok_or_else(|| {
                Refusal::new(
                    "denied",
                    "Hermes requires an initiating member's private conversation scope.",
                )
            })?;
            let profile = hermes_profile_id(scope, &root, external, &before.connection_revision)?;
            let home = app
                .path()
                .app_data_dir()
                .map_err(|_| Refusal::new("io", "The native profile directory is unavailable."))?
                .join("hermes-profiles")
                .join(profile);
            tokio::fs::create_dir_all(&home)
                .await
                .map_err(|_| Refusal::new("io", "The private Hermes profile could not be created."))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                tokio::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))
                    .await
                    .map_err(|_| Refusal::new("io", "The private Hermes profile permissions could not be set."))?;
            }
            if !home.join("config.yaml").is_file() {
                app.dialog().message(format!("Set up this isolated Hermes profile before retrying.\n\nHERMES_HOME: {}\nPython: {}\n\nSet HERMES_HOME to this directory in your terminal, then use this Python with -m hermes_cli.main --profile default setup. For Nous Portal use -m hermes_cli.main --profile default auth add nous --type oauth. Do not copy an existing Hermes home or token files. This setup is specific to this private conversation and registration.", home.display(), external.program))
                    .title("Set up Hermes for this conversation").kind(MessageDialogKind::Info).show(|_| {});
                return Err(Refusal::new(
                    "denied",
                    "Complete the isolated Hermes setup shown on this computer, then retry. No model prompt was sent.",
                ));
            }
            let runtime = runtime
                .as_ref()
                .ok_or_else(|| Refusal::new("io", "Prepare the managed runtime first."))?;
            spawn_with_bridge(
                Path::new(&external.program),
                &[
                    "-I".into(),
                    runtime.hermes_adapter().to_string_lossy().into_owned(),
                    home.to_string_lossy().into_owned(),
                ],
                &runtime.directory,
                path_with(Path::new(&external.program)),
                external.provider,
                Keys::default(),
                platform_tools.then_some(runtime),
            )?
        } else {
            if let Some(selected) = pi_key {
                let prepared = pi_keys::Prepared::new(app, Path::new(&external.program), key.as_ref(), selected)
                    .await
                    .map_err(|message| Refusal::new("denied", message))?;
                let current = crate::settings::current(app);
                if current.connection_revision != before.connection_revision
                    || !current.external_agents.contains(external)
                {
                    let _ = tokio::fs::remove_dir_all(&prepared.agent_dir).await;
                    return Err(Refusal::new(
                        "denied",
                        "The connection or Pi registration changed. Start again.",
                    ));
                }
                if let Err(error) = authorized_root(app, args, &root.to_string_lossy()) {
                    let _ = tokio::fs::remove_dir_all(&prepared.agent_dir).await;
                    return Err(error);
                }
                let spawned = spawn_with_bridge(
                    Path::new(&external.program),
                    &external.args,
                    &root,
                    path_with(Path::new(&external.program)),
                    external.provider,
                    Keys {
                        pi: Some(&prepared),
                        gemini: None,
                        model: None,
                        grok_home: None,
                    },
                    runtime.as_ref().filter(|_| platform_tools),
                );
                if spawned.is_err() {
                    let _ = tokio::fs::remove_dir_all(&prepared.agent_dir).await;
                }
                spawned?
            } else if matches!(
                external.provider,
                crate::external_agents::Provider::Muse | crate::external_agents::Provider::MuseApiKey
            ) {
                if app.state::<accounts::AccountFlows>().is_busy() {
                    return Err(Refusal::new(
                        "denied",
                        "Finish the Muse account operation before starting a task.",
                    ));
                }
                let runtime = runtime
                    .as_ref()
                    .ok_or_else(|| Refusal::new("io", "Prepare the managed SDK runtime first."))?;
                spawn_with_bridge(
                    &runtime.node,
                    &[
                        runtime.muse_adapter().to_string_lossy().into_owned(),
                        external.program.clone(),
                    ],
                    &root,
                    path_with(&runtime.node),
                    external.provider,
                    Keys::default(),
                    platform_tools.then_some(runtime),
                )?
            } else {
                spawn_with_bridge(
                    Path::new(&external.program),
                    &external.args,
                    &root,
                    path_with(Path::new(&external.program)),
                    external.provider,
                    Keys {
                        pi: None,
                        gemini: gemini_key.as_ref(),
                        model: runtime_model.as_deref(),
                        grok_home: grok_home.as_deref(),
                    },
                    runtime.as_ref().filter(|_| platform_tools),
                )?
            }
        }
    } else if let (Some(runtime), Some(builtin)) = (&runtime, agent.builtin()) {
        spawn_with_bridge(
            &runtime.node,
            &[runtime.adapter(builtin).to_string_lossy().into_owned()],
            &runtime.directory,
            path_with(&runtime.node),
            crate::external_agents::Provider::Custom,
            Keys::default(),
            platform_tools.then_some(runtime),
        )?
    } else {
        return Err(Refusal::new("denied", "The agent has no launch configuration."));
    };
    session.builtin_id = agent.builtin();
    session.external_id = external.as_ref().map(|item| item.id.clone());
    session.workspace_root = Some(root);
    session.resume_key = key;
    session.opening_call = Some(call_id.to_owned());
    let id = uuid::Uuid::new_v4().simple().to_string();
    sessions.map.lock().await.insert(id.clone(), session);
    drop(slot);
    let auth_method = external.as_ref().and_then(|item| login_method(item.provider));
    let runtime_name = external.as_ref().map(|item| item.name.as_str());
    let configuration_policy = if external.as_ref().is_some_and(|item| launch_models(item.provider)) {
        "launch"
    } else {
        "session"
    };
    let model_prefix = external
        .as_ref()
        .filter(|item| item.provider == crate::external_agents::Provider::OpenCodeGo)
        .map(|_| "opencode-go/");
    let pi_provider = external.as_ref().and_then(|item| match item.provider {
        crate::external_agents::Provider::PiInception => Some("inception"),
        crate::external_agents::Provider::PiDeepseek => Some("deepseek"),
        crate::external_agents::Provider::PiOpenrouter => Some("openrouter"),
        _ => None,
    });
    let refresh_catalog = external.as_ref().is_some_and(|item| {
        matches!(
            item.provider,
            crate::external_agents::Provider::OpenCode
                | crate::external_agents::Provider::OpenCodeGo
                | crate::external_agents::Provider::MistralVibe
                | crate::external_agents::Provider::Kimi
                | crate::external_agents::Provider::QwenSubscription
                | crate::external_agents::Provider::Devin
        )
    });
    Ok(object(
        serde_json::json!({ "id": id, "session_id": resumed, "auth_method": auth_method, "runtime_name": runtime_name, "model_prefix": model_prefix, "refresh_catalog": refresh_catalog, "configuration_policy": configuration_policy, "protocol": protocol, "pi_provider": pi_provider, "gemini_key": gemini_key.is_some(), "platform_tools_version": if platform_tools { 1 } else { 0 } }),
    ))
}

async fn remember_running(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let id = args.get("id").and_then(Value::as_str).unwrap_or_default();
    let session_id = args
        .get("session_id")
        .and_then(Value::as_str)
        .ok_or_else(|| Refusal::new("denied", "That session identifier is not valid."))?;
    let sessions = app.state::<Sessions>();
    let map = sessions.map.lock().await;
    let session = map
        .get(id)
        .ok_or_else(|| Refusal::new("not_found", "That agent is not running."))?;
    // Pi resumes by file path, not the ACP identifier grammar. Only a reference
    // observed in this owned child's successful state reply can enter history.
    if !session.output.with(|lines| lines.accepts_reference(session_id)) {
        return Err(Refusal::new(
            "denied",
            "That session reference was not admitted by this runtime.",
        ));
    }
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

fn hermes_profile_id(
    scope: &str,
    root: &Path,
    registration: &crate::external_agents::Registration,
    connection: &str,
) -> Result<String, Refusal> {
    if scope.len() != 64 || !scope.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(Refusal::new(
            "denied",
            "A private Hermes conversation scope is required.",
        ));
    }
    let identity = serde_json::to_vec(&(
        scope,
        root.to_string_lossy(),
        &registration.id,
        &registration.revision,
        connection,
    ))
    .map_err(bad)?;
    Ok(format!("{:x}", Sha256::digest(identity)))
}

/// Account mutation holds CHANGING, so no native launch can race credential replacement.
pub async fn close_builtin(app: &AppHandle, id: crate::local_agents::AgentId) -> Result<(), String> {
    let sessions = app.state::<Sessions>();
    let stopped = take_builtin(&mut *sessions.map.lock().await, id);
    for output in stopped {
        tokio::time::timeout(Duration::from_secs(15), async {
            loop {
                let changed = output.changed.notified();
                if output.with(|kept| kept.exit.is_some()) {
                    break;
                }
                changed.await;
            }
        })
        .await
        .map_err(|_| "The previous agent has not stopped; credentials were not changed.".to_owned())?;
    }
    let agent = match id {
        crate::local_agents::AgentId::Codex => AgentId::Codex,
        crate::local_agents::AgentId::ClaudeCode => AgentId::ClaudeCode,
    };
    crate::settings::update(app, |settings| {
        settings.coding_sessions.retain(|item| item.key.agent != agent);
        settings.coding_consents.retain(|item| item.agent != agent);
    })?;
    Ok(())
}

fn take_builtin(map: &mut HashMap<String, Session>, id: crate::local_agents::AgentId) -> Vec<Arc<Output>> {
    let mut stopped = Vec::new();
    map.retain(|_, session| {
        if session.builtin_id != Some(id) {
            return true;
        }
        if let Some(kill) = session.kill.take() {
            let _ = kill.send(());
        }
        stopped.push(session.output.clone());
        false
    });
    stopped
}

/// Revocation or replacement discards every process using this local registration.
pub async fn close_external(app: &AppHandle, id: &str) -> Result<(), String> {
    let sessions = app.state::<Sessions>();
    let outputs = remove_external(&mut *sessions.map.lock().await, id);
    for output in outputs {
        await_stopped(&output).await?;
    }
    Ok(())
}

async fn await_stopped(output: &Arc<Output>) -> Result<(), String> {
    tokio::time::timeout(Duration::from_secs(15), async {
        loop {
            let changed = output.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if output.with(|kept| kept.exit.is_some()) {
                break;
            }
            changed.await;
        }
    })
    .await
    .map_err(|_| "The previous runtime has not stopped; credentials were not changed.".to_owned())
}

fn remove_external(map: &mut HashMap<String, Session>, id: &str) -> Vec<Arc<Output>> {
    let mut outputs = Vec::new();
    map.retain(|_, session| {
        let matches = session.external_id.as_deref() == Some(id);
        if matches {
            if let Some(kill) = session.kill.take() {
                let _ = kill.send(());
            }
            outputs.push(Arc::clone(&session.output));
        }
        !matches
    });
    outputs
}

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

    #[test]
    fn pi_continuation_only_accepts_a_file_observed_from_its_owned_child() {
        let file = std::env::temp_dir()
            .join("pi-zażółć-session.jsonl")
            .to_string_lossy()
            .into_owned();
        let mut lines = Lines {
            capture_pi_state: true,
            ..Lines::default()
        };
        assert!(!lines.accepts_reference(&file));
        lines.push(
            serde_json::json!({"type":"response","command":"get_state","success":true,"data":{"sessionFile":file}})
                .to_string(),
        );
        assert!(lines.accepts_reference(&file));
        assert!(!lines.accepts_reference("/other/account/session.jsonl"));
        assert!(!Lines::default().accepts_reference(&file));
        assert!(Lines::default().accepts_reference("acp-native_123"));
        for value in [
            Value::Null,
            Value::String("relative.jsonl".into()),
            Value::String("/bad\npath".into()),
            Value::String("x".repeat(4097)),
        ] {
            lines.push(serde_json::json!({"type":"response","command":"get_state","success":true,"data":{"sessionFile":value}}).to_string());
            assert!(!lines.accepts_reference(&file));
        }
        lines.push(
            serde_json::json!({"type":"response","command":"get_state","success":true,"data":{"sessionFile":file}})
                .to_string(),
        );
        lines.push(serde_json::json!({"type":"response","command":"get_state","success":false}).to_string());
        assert!(!lines.accepts_reference(&file));
    }

    #[test]
    fn muse_key_mode_requires_an_explicit_nonempty_environment_key() {
        let mut command = tokio::process::Command::new("unused");
        assert!(muse_key_environment(&mut command, None).is_err());
        assert!(muse_key_environment(&mut command, Some(std::ffi::OsStr::new(" "))).is_err());
        muse_key_environment(&mut command, Some(std::ffi::OsStr::new("test-key"))).unwrap();
        let selected = command.as_std().get_envs().find(|(name, _)| *name == "META_API_KEY");
        assert_eq!(
            selected.map(|(_, value)| value),
            Some(Some(std::ffi::OsStr::new("test-key")))
        );
    }

    #[test]
    fn hermes_state_is_bound_to_private_scope_registration_folder_and_connection() {
        let registration = crate::external_agents::Registration {
            provider: crate::external_agents::Provider::Hermes,
            id: "hermes".into(),
            name: "Hermes".into(),
            program: "/python".into(),
            args: vec![],
            revision: "one".into(),
        };
        let scope = "a".repeat(64);
        let first = hermes_profile_id(&scope, Path::new("/work"), &registration, "connection").unwrap();
        assert_eq!(first.len(), 64);
        assert_eq!(
            first,
            hermes_profile_id(&scope, Path::new("/work"), &registration, "connection").unwrap()
        );
        for (scope, root, revision, connection) in [
            ("b".repeat(64), "/work", "one", "connection"),
            (scope.clone(), "/other", "one", "connection"),
            (scope.clone(), "/work", "two", "connection"),
            (scope.clone(), "/work", "one", "other"),
        ] {
            let changed = crate::external_agents::Registration {
                revision: revision.into(),
                ..registration.clone()
            };
            assert_ne!(
                first,
                hermes_profile_id(&scope, Path::new(root), &changed, connection).unwrap()
            );
        }
        assert!(hermes_profile_id("../../shared", Path::new("/work"), &registration, "connection").is_err());
    }

    #[tokio::test]
    async fn an_account_change_stops_only_its_builtin_sessions() {
        let mut codex = shell("sleep 60");
        codex.builtin_id = Some(crate::local_agents::AgentId::Codex);
        let mut claude = shell("sleep 60");
        claude.builtin_id = Some(crate::local_agents::AgentId::ClaudeCode);
        let custom = shell("sleep 60");
        let mut map = HashMap::from([
            ("codex".into(), codex),
            ("claude".into(), claude),
            ("custom".into(), custom),
        ]);
        let stopped = take_builtin(&mut map, crate::local_agents::AgentId::Codex);
        assert_eq!(stopped.len(), 1);
        assert!(!map.contains_key("codex"));
        assert!(map.contains_key("claude") && map.contains_key("custom"));
        let (_, _, exit) = drain(&stopped[0], 0).await;
        assert!(exit.is_some());
        for (_, mut session) in map {
            let _ = session.kill.take().unwrap().send(());
        }
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

    #[tokio::test]
    async fn revocation_stops_external_tasks_even_without_a_resume_key() {
        let mut revoked = shell("sleep 60");
        revoked.external_id = Some("first".into());
        let output = Arc::clone(&revoked.output);
        let mut retained = shell("sleep 60");
        retained.external_id = Some("second".into());
        let mut sessions = HashMap::from([("revoked".into(), revoked), ("retained".into(), retained)]);
        remove_external(&mut sessions, "first");
        assert!(!sessions.contains_key("revoked"));
        assert!(sessions.contains_key("retained"));
        assert!(drain(&output, 0).await.2.is_some());
        remove_external(&mut sessions, "second");
    }

    #[test]
    fn qwen_subscription_drops_inherited_api_destination_overrides() {
        use std::ffi::OsStr;
        let mut command = tokio::process::Command::new("qwen");
        qwen_subscription_environment(&mut command);
        let environment: std::collections::BTreeMap<_, _> = command.as_std().get_envs().collect();
        for name in ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "DASHSCOPE_API_KEY"] {
            assert_eq!(environment.get(OsStr::new(name)), Some(&None));
        }
    }

    #[test]
    fn grok_account_disables_api_auth_and_both_inherited_key_names() {
        use std::ffi::OsStr;
        let mut command = tokio::process::Command::new("grok");
        grok_account_environment(&mut command);
        let environment: std::collections::BTreeMap<_, _> = command.as_std().get_envs().collect();
        assert_eq!(environment.get(OsStr::new("XAI_API_KEY")), Some(&None));
        assert_eq!(environment.get(OsStr::new("GROK_CODE_XAI_API_KEY")), Some(&None));
        assert_eq!(
            environment.get(OsStr::new("GROK_DISABLE_API_KEY_AUTH")),
            Some(&Some(OsStr::new("true")))
        );
    }

    #[test]
    fn vibe_template_sets_child_only_privacy_and_catalog_options() {
        use std::ffi::OsStr;
        let mut command = tokio::process::Command::new("vibe-acp");
        vibe_environment(&mut command);
        let environment: std::collections::BTreeMap<_, _> = command.as_std().get_envs().collect();
        assert_eq!(
            environment.get(OsStr::new("VIBE_ENABLE_TELEMETRY")),
            Some(&Some(OsStr::new("false")))
        );
        assert_eq!(
            environment.get(OsStr::new("VIBE_EXPERIMENTAL_ENABLE_MODEL_CATALOG")),
            Some(&Some(OsStr::new("true")))
        );
        assert!(!environment.contains_key(OsStr::new("MISTRAL_API_KEY")));
    }

    #[test]
    fn a_vault_gemini_key_is_validated_redacted_and_wins_over_the_inherited_key() {
        use std::ffi::OsStr;
        assert!(serde_json::from_value::<GeminiKey>(serde_json::json!("short")).is_err());
        assert!(serde_json::from_value::<GeminiKey>(serde_json::json!("has space-1234")).is_err());
        let key: GeminiKey = serde_json::from_value(serde_json::json!("AIza-vault-key")).unwrap();
        assert_eq!(format!("{key:?}"), "GeminiKey([redacted])");
        let mut keyed = tokio::process::Command::new("agy");
        provider_environment(
            &mut keyed,
            crate::external_agents::Provider::AntigravityApiKey,
            Some(&key),
        )
        .unwrap();
        let environment: std::collections::BTreeMap<_, _> = keyed.as_std().get_envs().collect();
        assert_eq!(
            environment.get(OsStr::new("GEMINI_API_KEY")),
            Some(&Some(OsStr::new("AIza-vault-key")))
        );
        let mut account = tokio::process::Command::new("agy");
        provider_environment(&mut account, crate::external_agents::Provider::Antigravity, Some(&key)).unwrap();
        let environment: std::collections::BTreeMap<_, _> = account.as_std().get_envs().collect();
        assert_eq!(environment.get(OsStr::new("GEMINI_API_KEY")), Some(&None));
    }

    #[test]
    fn antigravity_account_and_key_modes_never_share_a_credential_fallback() {
        use std::ffi::OsStr;
        let mut account = tokio::process::Command::new("agy");
        antigravity_environment(&mut account, false, Some(OsStr::new("inherited-key"))).unwrap();
        let environment: std::collections::BTreeMap<_, _> = account.as_std().get_envs().collect();
        for name in [
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENAI_USE_VERTEXAI",
            "GOOGLE_GENAI_USE_GCA",
        ] {
            assert_eq!(environment.get(OsStr::new(name)), Some(&None));
        }
        for key in [None, Some(OsStr::new("")), Some(OsStr::new(" "))] {
            let refused = antigravity_environment(&mut tokio::process::Command::new("agy"), true, key).unwrap_err();
            assert!(refused.message.contains("saved Google sign-in was not used"));
        }
        let mut keyed = tokio::process::Command::new("agy");
        antigravity_environment(&mut keyed, true, Some(OsStr::new("explicit-key"))).unwrap();
        let environment: std::collections::BTreeMap<_, _> = keyed.as_std().get_envs().collect();
        assert_eq!(
            environment.get(OsStr::new("GEMINI_API_KEY")),
            Some(&Some(OsStr::new("explicit-key")))
        );
        assert_eq!(environment.get(OsStr::new("GOOGLE_GENAI_USE_VERTEXAI")), Some(&None));
    }

    #[test]
    fn cline_account_and_key_modes_never_share_a_credential_fallback() {
        use std::ffi::OsStr;
        let mut account = tokio::process::Command::new("cline");
        cline_environment(&mut account, false, Some(OsStr::new("inherited-key"))).unwrap();
        let environment: std::collections::BTreeMap<_, _> = account.as_std().get_envs().collect();
        assert_eq!(
            environment.get(OsStr::new("CLINE_PROVIDER")),
            Some(&Some(OsStr::new("cline")))
        );
        assert_eq!(environment.get(OsStr::new("CLINE_API_KEY")), Some(&None));
        for key in [None, Some(OsStr::new("")), Some(OsStr::new(" "))] {
            assert!(cline_environment(&mut tokio::process::Command::new("cline"), true, key).is_err());
        }
        let mut keyed = tokio::process::Command::new("cline");
        cline_environment(&mut keyed, true, Some(OsStr::new("explicit-key"))).unwrap();
        let environment: std::collections::BTreeMap<_, _> = keyed.as_std().get_envs().collect();
        assert_eq!(
            environment.get(OsStr::new("CLINE_PROVIDER")),
            Some(&Some(OsStr::new("cline")))
        );
        assert_eq!(
            environment.get(OsStr::new("CLINE_API_KEY")),
            Some(&Some(OsStr::new("explicit-key")))
        );
    }

    #[test]
    fn cursor_account_drops_inherited_api_modes_without_touching_cli_files() {
        let mut command = tokio::process::Command::new("cursor-agent");
        cursor_account_environment(&mut command);
        let environment: std::collections::BTreeMap<_, _> = command.as_std().get_envs().collect();
        assert_eq!(environment.get(std::ffi::OsStr::new("CURSOR_API_KEY")), Some(&None));
        assert_eq!(environment.get(std::ffi::OsStr::new("CURSOR_AUTH_TOKEN")), Some(&None));
        assert_eq!(
            environment.get(std::ffi::OsStr::new("NO_OPEN_BROWSER")),
            Some(&Some(std::ffi::OsStr::new("1")))
        );
    }

    #[test]
    fn external_continuations_are_bound_to_registration_revision() {
        let key = ResumeKey {
            scope: "a".repeat(64),
            root: "/work".into(),
            connection: "connection".into(),
            agent: AgentId::Custom,
            external: Some(ExternalIdentity {
                id: "agent".into(),
                revision: "old".into(),
            }),
        };
        let changed = ResumeKey {
            external: Some(ExternalIdentity {
                id: "agent".into(),
                revision: "new".into(),
            }),
            ..key.clone()
        };
        assert_ne!(key, changed);
        let remembered = Remembered {
            key: key.clone(),
            session_id: "session".into(),
        };
        assert!(remembered.is_for_external("agent"));
        assert!(!remembered.is_for_external("other"));
        let consent = Consent {
            external: key.external.clone(),
            ..Consent::new(Path::new("/work"), "connection", AgentId::Custom)
        };
        assert!(consent.is_for_external("agent"));
        assert!(!consent.is_for_external("other"));
        let old: ResumeKey = serde_json::from_value(
            serde_json::json!({"scope":"old", "root":"/work", "connection":"connection", "agent":"codex"}),
        )
        .unwrap();
        assert!(old.external.is_none());
    }

    #[tokio::test]
    async fn argument_values_are_passed_without_shell_expansion() {
        let mut session = spawn(
            Path::new("/usr/bin/printf"),
            &["%s\n".into(), "$HOME; touch /never-execute".into()],
            &std::env::temp_dir(),
            None,
        )
        .unwrap();
        let (lines, _, _) = drain(&session.output, 0).await;
        assert_eq!(lines, vec!["$HOME; touch /never-execute"]);
        session.kill.take();
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
                platform_tools: true,
                ..consent.clone()
            },
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
            external: None,
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

#[cfg(test)]
mod key_mode_tests {
    use super::*;
    use crate::external_agents::Provider;
    use std::ffi::OsStr;

    #[test]
    fn key_templates_require_a_key_and_remove_account_overrides() {
        for provider in [Provider::CursorApiKey, Provider::GrokApiKey] {
            let mut command = tokio::process::Command::new("unused");
            assert!(api_key_environment(&mut command, provider, None).is_err());
            assert!(api_key_environment(&mut command, provider, Some(OsStr::new("  "))).is_err());
            api_key_environment(&mut command, provider, Some(OsStr::new("explicit-test-key"))).unwrap();
            let environment: std::collections::HashMap<_, _> = command.as_std().get_envs().collect();
            if provider == Provider::CursorApiKey {
                assert_eq!(environment.get(OsStr::new("CURSOR_AUTH_TOKEN")), Some(&None));
                assert_eq!(
                    environment.get(OsStr::new("CURSOR_API_KEY")),
                    Some(&Some(OsStr::new("explicit-test-key")))
                );
            } else {
                assert_eq!(environment.get(OsStr::new("GROK_CODE_XAI_API_KEY")), Some(&None));
                assert_eq!(environment.get(OsStr::new("GROK_AUTH_PROVIDER_COMMAND")), Some(&None));
                assert_eq!(
                    environment.get(OsStr::new("XAI_API_KEY")),
                    Some(&Some(OsStr::new("explicit-test-key")))
                );
            }
        }
    }

    #[test]
    fn retained_grok_profile_removes_credentials_but_keeps_session_data() {
        let temporary = key_mode_home().unwrap();
        let retained = KeyModeHome(temporary.0.clone(), true);
        private_key_directory(&retained.0).unwrap();
        std::fs::write(retained.0.join("auth.json"), "vendor-written-key").unwrap();
        std::fs::write(retained.0.join("session.json"), "continuation").unwrap();
        drop(retained);
        assert!(!temporary.0.join("auth.json").exists());
        assert_eq!(
            std::fs::read_to_string(temporary.0.join("session.json")).unwrap(),
            "continuation"
        );
    }

    #[test]
    fn grok_key_profiles_are_private_unique_and_removed_on_drop() {
        let first = key_mode_home().unwrap();
        let second = key_mode_home().unwrap();
        assert_ne!(first.0, second.0);
        assert!(!first.0.join("auth.json").exists());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(std::fs::metadata(&first.0).unwrap().permissions().mode() & 0o777, 0o700);
        }
        std::fs::write(first.0.join("auth.json"), "vendor-written-key").unwrap();
        let path = first.0.clone();
        drop(first);
        assert!(!path.exists());
        assert!(second.0.exists());
    }
}
